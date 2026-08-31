# Domain Events & the Transactional Outbox

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/common/entities/base.py`](../../../../src/app/core/common/entities/base.py) — `Entity.record_event()` / `collect_events()`
    - [`src/app/core/common/events/domain_event.py`](../../../../src/app/core/common/events/domain_event.py) — `DomainEvent`, `to_payload()` / `from_payload()`
    - [`src/app/core/common/events/user_registered.py`](../../../../src/app/core/common/events/user_registered.py) — `UserRegisteredEvent`
    - [`src/app/core/common/events/handlers/send_welcome_email.py`](../../../../src/app/core/common/events/handlers/send_welcome_email.py) — `SendWelcomeEmail`, a `"background"`-mode handler
    - [`src/app/outbound/adapters/hybrid_event_dispatcher.py`](../../../../src/app/outbound/adapters/hybrid_event_dispatcher.py) — `HybridEventDispatcher`
    - [`src/app/outbound/adapters/outbox_message.py`](../../../../src/app/outbound/adapters/outbox_message.py) — `OutboxMessage`
    - [`src/app/outbound/adapters/sqla_outbox_repository.py`](../../../../src/app/outbound/adapters/sqla_outbox_repository.py) — `SqlaOutboxRepository`
    - [`src/app/main/worker/outbox_drain_loop.py`](../../../../src/app/main/worker/outbox_drain_loop.py) — the worker's own polling relay
    - [`src/app/main/worker/tasks.py`](../../../../src/app/main/worker/tasks.py) — `dispatch_event_handler_task`, the one Celery task every background handler runs under
    - [`src/app/main/worker/celery_app.py`](../../../../src/app/main/worker/celery_app.py) — worker process bootstrap, `worker_process_init`/`worker_process_shutdown`

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

A **Domain Event** — one of Domain-Driven Design's core building blocks, a record that something happened (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are) for the concept in full) — is easy to record in memory; this page is about what it takes to get one *reliably delivered*, in the specific case where delivery has to survive a process crash, a broker outage, or a worker restart.

## The end-to-end picture, before any of the detail

!!! figure "Entity records an event, outbox makes it durable, worker relays it"
    ```mermaid
    sequenceDiagram
        autonumber
        actor Client
        participant App as SignUp.execute()
        participant Postgres
        participant Worker as worker (drain loop)
        participant Redis
        participant Task as worker (dispatch_handler task)

        rect rgb(224, 240, 255)
        note over Client,Postgres: One HTTP request, one atomic transaction
        Client->>App: POST /account/signup/
        App->>App: UserService creates User,<br/>user.record_event(UserRegisteredEvent(...))
        App->>Postgres: session.add(user) -- BEGIN, still open
        App->>App: events = user.collect_events()
        App->>Postgres: dispatcher.stage(events):<br/>INSERT INTO event_outbox (same session)
        App->>Postgres: flush() + commit()
        note over App,Postgres: user row + outbox row commit together, or not at all
        App->>App: dispatcher.dispatch(events): runs any "sync" handlers now
        App-->>Client: 200/201 response
        end

        note over Client,Redis: request already answered -- everything below runs later, on its own clock

        rect rgb(255, 240, 214)
        loop every CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS
            Worker->>Postgres: SELECT ... WHERE processed_at IS NULL FOR UPDATE SKIP LOCKED
            alt row(s) pending
                Postgres-->>Worker: pending OutboxMessage row(s)
                Worker->>Redis: send_task(dispatch_handler, task_id=row.id)
                Worker->>Worker: mark_processed(row) -- in memory only
                Worker->>Postgres: commit() once for the whole batch
            else nothing pending
                Worker->>Worker: no-op -- no Celery/Redis traffic this tick
            end
        end
        end

        rect rgb(224, 247, 224)
        Redis->>Task: picks up dispatch_handler (task_id == outbox row's own id)
        Task->>Task: reconstruct event + handler from dotted paths,<br/>handler.handle(event) -- e.g. send the welcome email
        Task->>Redis: store result under celery-task-meta-<task_id>
        end
    ```

    > The single most important thing this diagram shows: there are **two independent timelines**. The client gets its response the moment the blue box ends — nothing in the yellow or green boxes ever makes it wait.

## The "dual write" problem this exists to solve

A use case like `SignUp` does two things that look like one atomic step but aren't: it changes domain state (a user registered) *and* it needs to reliably tell the rest of the system that happened (send a welcome email). The state change lives in Postgres. Once Celery is involved, the notification lives in Redis (the broker) and, eventually, a separate worker process. Those are two independent systems with no shared transaction. Whatever order you do them in, something can fail *between* them:

- **Commit, then publish** (the original design): the process crashes, or Redis is briefly unreachable, after the commit but before the publish. The user is registered — but the welcome email is silently never queued. No error, no retry, no trace; the event is just gone.
- **Publish, then commit**: the reverse trade — the notification goes out for a domain change that then never actually commits.

This is a well-known distributed-systems pattern called the "dual write problem" — not specific to Celery, Redis, or this codebase. It shows up anywhere a state change and a notification about that change are written to two different systems with no shared transaction between them.

**The fix:** stop treating "notify" as a second operation against a second system. Instead, make it a *write to the same database, in the same transaction* as the state change. Concretely: instead of publishing to Celery directly, the code writes one row to an `event_outbox` table — same Postgres database, same `AsyncSession`, same transaction that's about to commit the domain change. Postgres already guarantees that transaction is all-or-nothing, so "the domain change happened" and "we owe a notification" become the *same fact*, atomic by construction, with no second system involved yet. A separate process (the worker) later polls that table and does the actual delivery — which can fail and retry freely, since the row just sits there marked "not yet processed" until the next poll succeeds.

## `record_event()` / `collect_events()`: how an entity announces something happened

[`Entity.record_event(event)`](../../../../src/app/core/common/entities/base.py) — `Entity` being the base class every DDD **Entity** in `core` inherits from (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are) for what makes something an Entity) — appends a `DomainEvent` to a private in-memory list; [`collect_events()`](../../../../src/app/core/common/entities/base.py) returns and clears that list. Neither method touches the database — recording an event is purely an in-memory side effect of a domain operation, decoupled from *how* it's eventually handled. `UserService.create_user_with_raw_password()` calls `user.record_event(UserRegisteredEvent(...))` the moment it builds a new `User`; the use case (`SignUp`/`CreateUser`) calls `collect_events()` once, right after adding the entity to storage, and threads the resulting list through `stage()` then `dispatch()` (see [Transaction Management](transaction-management.md) for the full commit-boundary sequence). Per `collect_events()`'s own docstring, this is deliberate: "Events are collected after the use case commits" is the *conceptual* model even though, as this page covers next, staging now happens *before* the commit.

`DomainEvent` itself ([`domain_event.py`](../../../../src/app/core/common/events/domain_event.py)) is a frozen, `kw_only` dataclass with one universal field (`occurred_at`) plus whatever a concrete event adds — [`UserRegisteredEvent`](../../../../src/app/core/common/events/user_registered.py) adds `user_id`, `username`, `email`. `to_payload()`/`from_payload()` give every event a generic JSON (JavaScript Object Notation) round-trip, driven by `dataclasses.fields()` + `typing.get_type_hints()` with a small `_ENCODERS`/`_DECODERS` table (`datetime` ↔ isoformat string, `UUID` (Universally Unique Identifier) ↔ str, with `NewType.__supertype__` unwrapped first) — this is what actually crosses the wire in a Celery message body.

## Per-handler dispatch mode: `"sync"` vs `"background"`

Every [`EventHandler`](../../../../src/app/core/common/ports/event_handler.py) declares its own `DISPATCH_MODE: ClassVar[Literal["sync", "background"]]` right next to `handle()` — there is no default on the Protocol, so a handler that forgets it fails Protocol conformance under `mypy` the moment it's placed in the handler registry (`CoreProvider.provide_handler_registry`). This is deliberately **per-handler**, not a single app-wide toggle: one event type could in principle have one handler that must block the response (`"sync"`) and another that can safely lag (`"background"`), each declaring its own mode independently.

[`SendWelcomeEmail`](../../../../src/app/core/common/events/handlers/send_welcome_email.py) — the one real handler in this codebase today — declares `DISPATCH_MODE = "background"`: the new user doesn't need to wait for their welcome email before the signup response returns.

!!! figure "Where DISPATCH_MODE sends an event, inside HybridEventDispatcher"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        stage["stage(events)<br/>(called pre-commit)"]
        dispatch["dispatch(events)<br/>(called post-commit)"]

        subgraph stageLogic["stage() routing"]
            sBg{"handler.DISPATCH_MODE ==<br/>'background' AND<br/>Celery enabled?"}
            sWrite["write one OutboxMessage row<br/>(same open transaction)"]
            sSkip["no-op"]
        end

        subgraph dispatchLogic["dispatch() routing"]
            dSync{"handler.DISPATCH_MODE == 'sync'<br/>OR Celery disabled?"}
            dRun["await handler.handle(event) inline, now"]
            dAlreadyStaged["skip -- already staged,<br/>worker will relay it"]
        end

        stage --> sBg
        sBg -->|yes| sWrite
        sBg -->|no| sSkip

        dispatch --> dSync
        dSync -->|yes| dRun
        dSync -->|no| dAlreadyStaged

        linkStyle default stroke-width:3px,stroke:#333333
        style stageLogic stroke-width:1px,stroke:#333333
        style dispatchLogic stroke-width:1px,stroke:#333333
    ```

    > Reading both branches together: a `"sync"` handler is never staged (its `stage()` condition is always false) and always runs inline in `dispatch()`. A `"background"` handler, with Celery enabled, is staged pre-commit and explicitly skipped in `dispatch()` — the outbox and the worker's drain loop own its delivery from there. With Celery *disabled* (`CELERY_ENABLED=false`), `stage()` never writes a row (nothing to relay to), and `dispatch()`'s `or not self._celery_enabled` clause makes every handler — sync or background — run inline instead: a deployment can skip Redis/Celery entirely and every handler still reliably runs, just without the background lag.

## Why `HybridEventDispatcher` has two methods, not one

[`HybridEventDispatcher`](../../../../src/app/outbound/adapters/hybrid_event_dispatcher.py) exposes both halves of the [`EventDispatcher`](../../../../src/app/core/common/ports/event_dispatcher.py) port:

```python
async def stage(self, events: list[DomainEvent]) -> None:
    """Call BEFORE the caller's own flush()/commit()."""

async def dispatch(self, events: list[DomainEvent]) -> None:
    """Call AFTER the caller's own commit()."""
```

`stage()` is what actually closes the dual-write gap: it writes an `OutboxMessage` row, via `OutboxRepository.add()`, into the *same* `AsyncSession` the caller's own `flush()`/`commit()` will act on next — see [Transaction Management](transaction-management.md) for the full sequence this participates in. `dispatch()` is unchanged in spirit from the original, pre-outbox design; it just skips anything `stage()` already durably recorded, so nothing runs twice.

## The `OutboxRepository` port stays minimal on purpose

[`OutboxRepository`](../../../../src/app/core/commands/ports/outbox_repository.py), the `core`-level port, declares exactly one method: `add()`. That's the only operation `stage()` (running in `core`'s call graph, pre-commit) actually needs. Everything the worker needs later — `get_pending()`, `mark_processed()`, `delete()`, `commit()` — lives only on the concrete [`SqlaOutboxRepository`](../../../../src/app/outbound/adapters/sqla_outbox_repository.py) adapter, which `app.main.worker.outbox_drain_loop` imports and calls directly by its concrete class. This is allowed because `main` may import `outbound` freely (just never the reverse — see [Ports and Adapters](ports-and-adapters.md)), and it keeps the core port from being inflated with methods only one worker-side consumer ever calls.

## `get_pending()`: `FOR UPDATE SKIP LOCKED`, and why it has to be there

Celery's prefork pool starts `CELERY_WORKER_CONCURRENCY` separate child processes (2 by default here), and each one independently runs its own copy of the outbox drain loop — plus a production deployment might run several `worker` containers. Without row-level locking, two of these loops polling at the same moment could both see, and both relay, the same still-pending row. `SqlaOutboxRepository.get_pending()` uses `select(...).with_for_update(skip_locked=True)`: it locks every row it returns and skips any row a concurrent call already has locked, so two concurrent batches are always disjoint.

That lock has to survive for the *whole batch*, which is why `mark_processed()`/`delete()` don't commit themselves — a separate `commit()` method does, called exactly once after every row in the batch has been relayed and marked. Committing per-row would release the lock on that same batch's own remaining rows immediately, letting a concurrent loop see them as unlocked and pending again — reopening the exact race the locking exists to close.

## Retention: `processed_at` instead of deleting on relay

`event_outbox` rows are retained by default (`CELERY_OUTBOX_RETAIN_AFTER_RELAY=true`) rather than deleted the instant they're relayed — deliberately, so the table stays inspectable (via Adminer) as an audit trail of every event that ever fired, not an invisible, self-erasing queue. This means "a row exists" can no longer mean "pending" once relayed rows can stick around — hence [`OutboxMessage`](../../../../src/app/outbound/adapters/outbox_message.py)'s nullable `processed_at` column, set the moment a row is relayed, regardless of the retention setting. `get_pending()`'s `WHERE processed_at IS NULL` is what actually distinguishes pending from already-relayed. Only when retention is explicitly turned off does the drain loop additionally call `delete()`.

## Why the relay is a plain polling loop, not a Celery Beat task

[`outbox_drain_loop.py`](../../../../src/app/main/worker/outbox_drain_loop.py)'s `_run_forever()` is a plain `asyncio` coroutine, spawned once per worker process (via `loop_runtime.spawn()`, from `celery_app.py`'s `worker_process_init` signal) and cancelled on `worker_process_shutdown` — not a Celery Beat-scheduled task. This was tried as a Beat task first and changed after observing the real running system: a Celery task, even an empty no-op tick, still publishes through the broker and shows up in Flower's live task list, and — unless explicitly marked `ignore_result=True` — writes a `celery-task-meta-*` key to the Redis result backend, on *every* tick, whether or not there was anything to drain. Over a day of mostly-idle uptime, that's tens of thousands of "did nothing" entries — noise scaling with uptime, not with actual events. A plain coroutine loop on the worker's own persistent event loop never touches the broker or result backend on an empty tick, so the only Celery tasks that ever exist are real, one-per-outbox-row `dispatch_handler` tasks: Postgres, Flower, and Redis stay a 1:1 mirror of each other.

A failed tick inside `_run_forever()` is logged and swallowed (`except Exception`), not left to kill the loop — a single bad tick (a transient DB (database) blip) shouldn't permanently stop draining for the rest of the process's life. `CancelledError`, raised by `stop()`'s `future.cancel()`, is deliberately left to propagate, since that's the loop's intended way to end.

## The shared id: one UUID across Postgres, Celery, and Redis

`SqlaOutboxRepository.add()` generates the outbox row's own `id_` as a `uuid7()` — time-sortable, the same scheme `id_factory.create_user_id()` already uses for `User` — rather than letting the database assign an autoincrement integer. The drain loop passes that same id as the Celery task's `task_id` (`send_task(DISPATCH_HANDLER_TASK_NAME, task_id=str(message.id_), ...)`), which becomes the Redis result key too (`celery-task-meta-<id>`). One id, traceable across all three places a relayed event ever shows up — the `event_outbox` row, the Celery task in Flower, and its Redis result entry — which is what makes a specific event's delivery actually auditable rather than merely "probably fine." A plain autoincrement int would technically work as a `task_id` too, but risks eventually colliding with some unrelated id scheme reusing small integers; a UUID rules that out by construction.

## Why the worker needs a persistent event loop at all

Celery's default worker pool has no native `async`/`await` support — a task body is plain synchronous Python. [`loop_runtime.py`](../../../../src/app/main/worker/loop_runtime.py) starts exactly one `asyncio` event loop per worker *process*, running in a background thread for the process's whole life, rather than each task calling `asyncio.run()` on a fresh loop of its own. This matters the moment any async resource is cached for the whole process — the SQLAlchemy `AsyncEngine`, built once at `Scope.APP`, is bound to whichever event loop existed when it was first used. A fresh `asyncio.run()` per task would eventually raise "Future attached to a different loop" the first time two different tasks' fresh loops both touched that same cached engine. `run_coroutine()` schedules a coroutine onto this one persistent loop and blocks the calling (Celery) thread for its result — how `dispatch_event_handler_task` in [`tasks.py`](../../../../src/app/main/worker/tasks.py) actually runs `handler.handle(event)`; `spawn()` does the same but without blocking, used for the drain loop, which is meant to run for the process's whole life rather than return a result to anyone.

## Where to go next

- [Ports and Adapters (Repository Pattern)](ports-and-adapters.md) — the `EventDispatcher`/`EventHandler`/`OutboxRepository` ports in the context of every other port/adapter pair.
- [Dependency Injection with Dishka](dependency-injection.md) — why the worker builds its own container (`WorkerProvider`) instead of reusing the web process's, and how the two `AsyncSession`-bound sessions get resolved.
- [Transaction Management (Unit of Work-style)](transaction-management.md) — the commit-boundary sequence `stage()` slots into, in full.
