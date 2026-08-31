# Background Jobs (Celery / Redis)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/celery_factory.py`](../../../../src/app/main/celery_factory.py) — `build_celery_app()`, the one factory both processes below call
    - [`src/app/main/worker/`](../../../../src/app/main/worker/) — the worker's own composition root: `celery_app.py`, `loop_runtime.py`, `container.py`, `provider.py`, `outbox_drain_loop.py`, `tasks.py`
    - [`src/app/outbound/adapters/hybrid_event_dispatcher.py`](../../../../src/app/outbound/adapters/hybrid_event_dispatcher.py) — `HybridEventDispatcher`, the web process's half of this mechanism
    - [`src/app/outbound/adapters/sqla_outbox_repository.py`](../../../../src/app/outbound/adapters/sqla_outbox_repository.py) — `get_pending()`/`mark_processed()`/`delete()`/`commit()`, called only by the worker's drain loop
    - [`src/app/core/common/ports/event_handler.py`](../../../../src/app/core/common/ports/event_handler.py) — the `EventHandler` **port** (an abstract interface `core` declares without knowing which concrete adapter satisfies it — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)), carrying the per-handler `DISPATCH_MODE`
    - [`docker-compose.yml`](../../../../docker-compose.yml) — the `redis`, `worker`, `flower`, `redis-commander` services
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — the `worker)` case
    - [`env.example`](../../../../env.example) — every `REDIS_*`/`CELERY_*`/`FLOWER_PORT`/`REDIS_COMMANDER_PORT` variable
    - [`docs/plans/3-celery-redis-events.md`](../../../../docs/plans/3-celery-redis-events.md) — the implementation plan this whole mechanism was built from

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Why a second composition root

A Celery worker runs in its own OS (Operating System) process — no HTTP (Hypertext Transfer Protocol) request, no access to the web process's Dishka container, no FastAPI app object. [`src/app/main/worker/`](../../../../src/app/main/worker/) is a second, independent composition root (the one place, per process, that wires concrete adapters to the ports `core`/`core`-adjacent code declares — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)) built specifically for that: its own persistent `asyncio` event loop, its own `AsyncContainer`, its own `Celery` object (built by the same `build_celery_app()` factory the web process uses, but never the same Python object — they only agree on the broker URL (Uniform Resource Locator) and one task-name string). See [`docs/plans/3-celery-redis-events.md`](../../../../docs/plans/3-celery-redis-events.md) for the full reasoning, including why `WorkerProvider` (in `provider.py`) is a wholly independent Dishka provider rather than a reuse or split of the web process's `CoreProvider`/`AuthProvider` — reusing them made the worker's container-build fail validation, since Dishka checks the *entire* declared graph, and `CoreProvider` unconditionally declares things (like `CurrentUserService`) that need a real Starlette `Request`.

!!! figure "Worker process startup, then two concurrent loops for its whole life"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph init["worker_process_init (once, before any task runs)"]
            maptables["map_tables()"] --> startloop["start_loop()\n(one asyncio loop, its own thread)"]
            startloop --> buildcontainer["build_worker_container()\n(Scope.APP Dishka container)"]
            buildcontainer --> drainstart["outbox_drain_loop.start()"]
        end

        subgraph consume["Loop A: consuming Celery tasks"]
            queue[("redis: events queue")] --> task["dispatch_event_handler_task"]
            task --> runcoro["run_coroutine(_dispatch)"]
            runcoro --> resolve["resolve handler via a per-task\nScope.REQUEST container"]
            resolve --> handle["handler.handle(event)"]
        end

        subgraph drain["Loop B: draining the outbox (own coroutine, no Celery Beat)"]
            tick["tick every\nCELERY_DRAIN_OUTBOX_INTERVAL_SECONDS"] --> getpending["get_pending()\n(SELECT ... FOR UPDATE SKIP LOCKED)"]
            getpending --> sendtask["send_task(...)\nper pending row"]
            sendtask --> markprocessed["mark_processed()\n(+ delete(), if configured)"]
            markprocessed --> commitbatch["commit() once,\nafter the whole batch"]
            commitbatch --> tick
        end

        drainstart --> queue
        drainstart --> tick
        sendtask --> queue

        linkStyle default stroke-width:3px,stroke:#333333
        style init stroke-width:1px,stroke:#333333
        style consume stroke-width:1px,stroke:#333333
        style drain stroke-width:1px,stroke:#333333
    ```

    > Both loops run inside the *same* worker process, on the *same* persistent event loop (`loop_runtime.py`) — there is no separate `beat` container. `_run_forever()` in [`outbox_drain_loop.py`](../../../../src/app/main/worker/outbox_drain_loop.py) is a plain `while True: ... await asyncio.sleep(...)` coroutine, deliberately not a Celery Beat-scheduled task: a Beat task still shows up in Flower/Redis on every tick even with nothing to drain, polluting the audit trail a Celery task is otherwise meant to be here (see the Celery-redis-events plan's "Why not a Celery Beat task" note). `get_pending()` uses `SELECT ... FOR UPDATE SKIP LOCKED` because more than one process can call it concurrently (Celery's prefork pool alone starts `CELERY_WORKER_CONCURRENCY` child processes) — locking keeps two concurrent drains from relaying the same row twice, and `commit()` only runs once per whole batch so those locks aren't released early mid-batch.

## The web process's side: stage before commit, dispatch after

`HybridEventDispatcher` never talks to Redis or Celery directly. Its `stage()` is called **before** the caller's `flush()`/`commit()` and writes one `event_outbox` row per (event, `"background"`-mode handler) pair, in the *same* database transaction as the state change that triggered the event — this is the [transactional outbox](database.md), closing the "dual write" gap a bare `send_task()` call after commit would otherwise leave open (a crash between commit and publish could silently drop the event). Its `dispatch()`, called **after** commit, only ever runs `"sync"`-mode handlers inline — a `"background"` handler is deliberately *not* run here when Celery is enabled, since the row `stage()` already wrote will be relayed by the worker's own drain loop; running it here too would run it twice.

!!! figure "Per-handler dispatch decision, including the CELERY_ENABLED=false fallback"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        exec["e.g. SignUp.execute()"] --> stage["event_dispatcher.stage(events)"]
        stage --> enabled1{"CELERY_ENABLED?"}
        enabled1 -->|true| outboxrow[("event_outbox row\nwritten, uncommitted")]
        enabled1 -->|false| noop["no-op\n(nothing to relay to)"]
        outboxrow --> commit["flush() + commit()"]
        noop --> commit
        commit --> dispatch["event_dispatcher.dispatch(events)"]
        dispatch --> mode{"handler.DISPATCH_MODE?"}
        mode -->|"sync"| inline["awaited inline,\nalways"]
        mode -->|"background AND CELERY_ENABLED"| skip["skipped here --\nworker's drain loop relays it"]
        mode -->|"background AND NOT CELERY_ENABLED"| fallback["awaited inline\n(Celery-less fallback)"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > This is the mechanism behind the `CELERY_ENABLED=false` inline fallback mentioned on the [Overview](../../index.md#what-actually-runs): a deployment that doesn't want to run Redis/a worker at all sets `CELERY_ENABLED=false`, and every handler — regardless of its own declared `DISPATCH_MODE` — ends up running synchronously inside the web request instead of being queued. Nothing errors and nothing silently drops; the deployment just loses the "don't block the response" benefit for handlers declared `"background"`. Today's one real handler is `SendWelcomeEmail` (see [Email (SMTP)](email.md)), declared `"background"` since a signup response shouldn't wait on an outgoing email.

## Which containers actually start

!!! figure "Celery-related containers, gated by CELERY_ENABLED and ENVIRONMENT"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        celeryenabled{"CELERY_ENABLED?"}
        celeryenabled -->|true| redis[("redis")]
        celeryenabled -->|true| worker["worker"]
        redis --> devcheck{"ENVIRONMENT=development\nAND CELERY_ENABLED=true?"}
        worker --> devcheck
        devcheck -->|yes| flower["flower\n:5555"]
        devcheck -->|yes| rediscommander["redis-commander\n:8081"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `redis` and `worker` sit behind Compose's `celery` profile (active whenever `CELERY_ENABLED=true` — `scripts/makefile/docker_env.sh`/`local_env.sh` derive `COMPOSE_PROFILES` from that one setting, so the two can never disagree). `flower` (Celery's task-monitoring dashboard, `http://localhost:5555`) and `redis-commander` (browses the raw Redis keys — the broker's `events` queue in `REDIS_DB`, task results in `REDIS_RESULT_DB` — the same way Adminer does for Postgres) additionally require `ENVIRONMENT=development`, via the `celery-development` profile. `worker`'s own healthcheck runs `celery ... inspect ping` against itself, with a generous 45s `start_period` to absorb CPU contention from every other service starting at once.

## `env.example`'s Celery/Redis variables

| Variable | Default | Notes |
|---|---|---|
| `CELERY_ENABLED` | `true` | the one switch controlling both the inline fallback above and which containers start |
| `REDIS_HOST` / `PORT` / `DB` / `RESULT_DB` / `PASSWORD` | `redis` / `6379` / `0` / `1` / *(empty)* | broker and result backend share one Redis instance, two logical DBs (databases); `REDIS_HOST` has the same Docker-vs-local rewrite gotcha as `POSTGRES_HOST` — see [Database (Postgres)](database.md) |
| `CELERY_TASK_DEFAULT_QUEUE` | `events` | |
| `CELERY_TASK_ACKS_LATE` | `true` | a task is only acked after it finishes, so a worker crash mid-task leaves it to be retried rather than lost |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | |
| `CELERY_WORKER_CONCURRENCY` | `2` | deliberately modest — Celery's own default is one process per CPU (Central Processing Unit) core |
| `CELERY_OUTBOX_RETAIN_AFTER_RELAY` | `true` | keep relayed outbox rows (queryable in Adminer) rather than deleting them |
| `CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS` | `3` | how often the drain loop above ticks |
| `FLOWER_PORT` / `REDIS_COMMANDER_PORT` | `5555` / `8081` | dev-only dashboard ports |

## Where to go next

- [Database (Postgres)](database.md) — the `event_outbox` table this worker drains.
- [Email (SMTP)](email.md) — `SendWelcomeEmail`, today's one real `"background"` handler, and the port/adapter it calls into.
- [Core Patterns → Domain Events & Outbox](../core-patterns/domain-events-outbox.md) — the domain-events mechanism this whole dispatch system serves.
