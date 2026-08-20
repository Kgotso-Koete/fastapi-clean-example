# Celery + Redis Background Dispatch with Per-Handler Sync/Background Control

> **Implementation Plan v0.7.0**
>
> Replaces the two asyncio-based event dispatchers (`SyncEventDispatcher`, `BackgroundEventDispatcher`) with a single `HybridEventDispatcher` that reads a **per-handler** `DISPATCH_MODE` and either awaits a handler inline or hands it off to Celery, backed by Redis. Migrates the one real handler (`SendWelcomeEmail`) onto the new mechanism as a `"background"` handler, and establishes a second composition root (`app.main.worker`) for the Celery worker process.

---

## Context

The current event system (`SyncEventDispatcher`/`BackgroundEventDispatcher`, built via `asyncio.create_task()`) works for today's one real handler (`SendWelcomeEmail`) but has two problems surfaced during a review of the actual code:

1. **No delivery guarantee.** Dishka's request-scoped container is disposed right after the HTTP response is sent (verified directly in `dishka/integrations/starlette.py`), before any `asyncio.create_task()`-scheduled work is guaranteed to finish, and `make_lifespan()` in `run.py` never drains in-flight background tasks on shutdown. A deploy or crash at the wrong moment silently drops the event.
2. **No sync/background control finer than "the whole app."** `EventSettings.DISPATCH_MODE` is a single global toggle. The actual need, illustrated with a concrete example (an `OrderPlaced` event where `NotifyUserOrderRegistration` must block the response but `CreateInvoice` can lag), requires per-**handler** control.

Celery + Redis was chosen over a Postgres-backed transactional outbox (discussed and set aside) for the industry-standard tooling, retry/monitoring story, and because order volume (300/day, expected to double or triple) plus a concrete near-term use case (an external distance-calculation API call, and eventually invoicing) justifies standing up the infrastructure now. This plan follows the repo's established TDD Red-Green-Refactor discipline (test files written and run RED before any production file is touched) and Clean Architecture layering (verified against `[tool.importlinter]`'s contracts throughout).

**Outcome:** `SendWelcomeEmail` runs via a real Celery worker process instead of `asyncio.create_task()`; every `EventHandler` declares its own `DISPATCH_MODE` (`"sync"` or `"background"`); a `HybridEventDispatcher` reads that per-handler and either awaits inline or publishes to Celery; a second composition root (`app.main.worker`) exists for the worker process; Redis, the worker, and Flower are new docker-compose services; and one real-broker smoke test proves the actual producer→broker→consumer wiring works end to end, on top of infra-free eager-mode unit/integration tests.

---

## Confirmed decisions

1. **Persistent per-worker event loop, built now** — not a naive `asyncio.run()` per task. More plumbing today, but avoids "Future attached to a different loop" the moment a DB-touching background handler (e.g. `CreateInvoice`) is added.
2. **Flower + a Redis result backend, added now** — not deferred.
3. **One real-broker smoke test, added now** — proves actual Redis wiring (queue name, serializer, task name) end to end, on top of eager-mode tests that never touch a real broker.

---

## Architectural decisions

### Dispatch mode lives on the handler, declared in code — no env var, no per-event-type toggle

`EventHandler[T]` (the core port, `src/app/core/common/ports/event_handler.py`) gains a required class attribute:

```python
DISPATCH_MODE: ClassVar[Literal["sync", "background"]]
```

Every concrete handler declares it right next to `handle()`. There's no default on the Protocol, so a handler that forgets it fails Protocol conformance (caught by `mypy`) the moment it's placed in a handler registry. `EventSettings.DISPATCH_MODE` (today's global env-var toggle) is **removed entirely** — the per-handler `ClassVar` is the replacement.

`SyncEventDispatcher` and `BackgroundEventDispatcher` are **deleted**, replaced by one `HybridEventDispatcher` that reads `handler.DISPATCH_MODE` per handler, per event, and either `await`s inline or publishes to Celery. `SendWelcomeEmail` still only depends on `EmailSender` — it doesn't know Celery exists, preserving the pub/sub decoupling the original events plan established.

### The process-boundary problem: a second composition root

Celery workers run in a separate OS process — no HTTP request, no access to the web process's Dishka container. This plan adds `src/app/main/worker/`, a second, independent composition root:

- **`loop_runtime.py`** — starts one persistent `asyncio` event loop in a background thread, for the life of the worker *process* (not per task). Every task's coroutine runs on this one loop via `asyncio.run_coroutine_threadsafe(...).result()`. This matters once a DB-touching background handler exists: an `AsyncEngine` cached at `Scope.APP` gets bound to whichever loop existed when it was first instantiated — a fresh `asyncio.run()` per task would eventually raise "Future attached to a different loop." Building one loop per process avoids this by construction.
- **`container.py`** — builds one `Scope.APP` Dishka container for the worker process (via `worker_process_init`), and opens one `Scope.REQUEST` child container per task (mirroring how `ContainerMiddleware` opens one per HTTP request).
- **`celery_app.py`** — builds the `Celery` app object for the worker process via the same factory the web process uses, wires the `worker_process_init`/`worker_process_shutdown` signals to the loop+container lifecycle.
- **`tasks.py`** — the single task, `app.events.dispatch_handler`, resolving the target handler from the per-task container and calling `.handle(event)`.

**Why the web process's `HybridEventDispatcher` never imports `app.main.worker.tasks`:** `import-linter`'s `layers` contract is `(main) -> inbound -> outbound -> core` — `outbound` may never import `main`. The dispatcher lives in `outbound` and publishes by **task name string only** (`celery_app.send_task("app.events.dispatch_handler", kwargs=...)`), which is also idiomatic Celery — producers routinely don't import task modules.

**Why no scope changes are needed on the web side:** `HybridEventDispatcher.dispatch()` awaits `celery_app.send_task(...)` — a fast, synchronous Redis publish, pushed off the event loop via `asyncio.to_thread` — to completion *before* `SignUp.execute()` returns and before the request's Dishka container is torn down. Nothing background-related keeps running in the web process afterward; the old `_background_tasks` strong-ref workaround and its associated Scope.REQUEST-lifetime risk disappear entirely, because handler *execution* now happens inside the worker process's own, separately-lived container.

### Serialization: `DomainEvent.to_payload()`/`from_payload()`

Generic, driven by `dataclasses.fields()` + `typing.get_type_hints()` (with `NewType.__supertype__` unwrapped), covering the vocabulary that exists today (`str`, `datetime`, `UUID`-via-`NewType`). Keeps Celery-specific knowledge (task names, dotted paths) in `outbound`, keeps `DomainEvent` itself transport-agnostic. A future event field type outside `{str, int, float, bool, datetime, UUID}` needs one new encoder/decoder entry — an accepted, narrow limitation.

### Why `build_celery_app` is a pure factory, not a singleton import

`outbound` may not import `app.main.config.settings` (already an import-linter contract; the one existing exception, `alembic/env.py`, is explicit and not a precedent to extend). So `src/app/outbound/adapters/celery_app.py` is a factory taking plain values (`broker_url`, `result_backend_url`, ...) — same pattern as `SmtpEmailSender.__init__(host: str, ...)`. The **web process** (`CeleryProvider` in `main/ioc/outbound.py`) and the **worker process** (`main/worker/celery_app.py`) each call this factory with their own DI-resolved or directly-loaded settings, ending up with their own `Celery` Python objects that agree only on the broker URL and the task-name string contract.

---

## Proposed Changes

### Step 1 — `DomainEvent` JSON payload round-trip (Core)

**TDD order:** extend `tests/unit/core/common/events/test_domain_event.py` and `test_user_registered.py` with round-trip tests (incl. a `datetime` field and a `NewType`-over-`UUID` field) → RED → then modify `src/app/core/common/events/domain_event.py` → GREEN.

Add `to_payload(self) -> dict[str, Any]` and `classmethod from_payload(cls, payload) -> Self`, driven by `dataclasses.fields()` + `get_type_hints()`, with a small `_ENCODERS`/`_DECODERS` dict (`datetime` ↔ isoformat, `UUID` ↔ str) and a `_unwrap_newtype` helper reading `__supertype__`.

### Step 2 — Per-handler `DISPATCH_MODE` + migrate `SendWelcomeEmail` (Core)

**TDD order:** extend `tests/unit/core/common/events/handlers/test_send_welcome_email.py` to assert `SendWelcomeEmail.DISPATCH_MODE == "background"` → RED → modify `src/app/core/common/ports/event_handler.py` (add `DISPATCH_MODE: ClassVar[Literal["sync", "background"]]`) and `send_welcome_email.py` (`DISPATCH_MODE: ClassVar[...] = "background"`) → GREEN.

### Step 3 — Celery app factory + event (de)serialization helpers (Outbound)

**TDD order:** write `tests/unit/outbound/adapters/test_celery_app.py` and `test_event_serialization.py` → RED → create both files → GREEN.

- **[NEW]** `src/app/outbound/adapters/celery_app.py` — `build_celery_app(*, broker_url, result_backend_url, default_queue, task_acks_late, worker_prefetch_multiplier) -> Celery`, JSON serializer, `task_ignore_result=False` (Flower + result backend need this).
- **[NEW]** `src/app/outbound/adapters/event_serialization.py` — `dotted_path(cls) -> str` (`"module:QualName"`) and `import_from_dotted_path(path) -> type`.

### Step 4 — `HybridEventDispatcher` (Outbound) — replaces both old dispatchers

**TDD order:** write `tests/unit/outbound/adapters/test_hybrid_event_dispatcher.py` (sync handler awaited inline; background handler triggers `celery_app.send_task` with `event_type`/`handler_type`/`payload` kwargs, via a mocked `Celery`; an event with *both* a sync and a background handler runs both correctly) → RED → create `src/app/outbound/adapters/hybrid_event_dispatcher.py` → GREEN → delete `sync_event_dispatcher.py`, `background_event_dispatcher.py`, and their old test files.

### Step 5 — Worker composition root (`src/app/main/worker/`)

**TDD order:** write `tests/unit/main/worker/test_loop_runtime.py`, `test_container.py`, `test_tasks.py` → RED → create all files below → GREEN.

- **[NEW]** `loop_runtime.py` — `start_loop()`/`stop_loop()`/`run_coroutine(coro)`.
- **[NEW]** `container.py` — `build_worker_container()`, `get_worker_container()`, `close_worker_container()`, plus explicit `set_worker_container(c)`/`clear_worker_container()` test helpers.
- **[NEW]** `celery_app.py` — builds `celery_app` via the shared factory, wires `worker_process_init`/`worker_process_shutdown` to `loop_runtime`+`container`, imports `tasks` last.
- **[NEW]** `tasks.py` — `@celery_app.task(name="app.events.dispatch_handler", bind=True, max_retries=3, default_retry_delay=10)`, resolving the handler from a per-task `Scope.REQUEST` container and calling `.handle(event)`.

### Step 6 — Settings: `RedisSettings`/`CelerySettings`, retire `EventSettings`

**TDD order:** update `tests/unit/main/config/test_loader.py` → RED → modify `settings.py`/`loader.py` → GREEN.

`RedisSettings(HOST, PORT, DB, RESULT_DB, PASSWORD, url, result_url)`, `CelerySettings(TASK_DEFAULT_QUEUE, TASK_ACKS_LATE, WORKER_PREFETCH_MULTIPLIER)`, following the exact existing `EmailSettings`/`EmailEnvConfig`/`load_email_settings()` three-part pattern.

### Step 7 — IoC wiring

- `main/ioc/outbound.py` — new `CeleryProvider(Provider)` (`Scope.APP`), same generator-cleanup pattern as `HasherThreadPoolProvider`. `outbound_providers(*, include_request_provider: bool = True)` gains the flag.
- `main/ioc/provider_registry.py` — add `get_worker_providers()`.
- `main/ioc/core.py` — `event_dispatcher = provide(HybridEventDispatcher, provides=EventDispatcher)`.

### Step 8 — Infra: docker-compose, entrypoint, Makefile, dependencies

- `docker-compose.yml`: `app` depends on `redis` (healthy); new `redis` (`redis:8-alpine`), `worker` (depends on `db_pg`+`redis` health only — **not** `app**, to avoid deadlocking the test flow where `app` is `run`, never `up`'d), `flower` services.
- `docker-compose.test.yml`: add `redis: ports: !reset []`.
- `docker-entrypoint.sh`: new `worker)` case running `celery -A app.main.worker.celery_app:celery_app worker`.
- `Makefile`: `INFRA_SERVICES ?= db_pg redis`; `test-docker-app` explicitly appends `worker` to its compose-up line (for the smoke test); `open-dashboards` gets a Flower line.
- `pyproject.toml`: `"celery[redis]==5.6.3"`.
- `env.example`/`.env`: drop `EVENT_DISPATCH_MODE`; add `REDIS_*`, `CELERY_*`, `FLOWER_PORT`.
- `README.md`: update events TODO line; add Flower URL.

### Step 9 — Tests

**Unit** (infra-free): payload round-trip; `DISPATCH_MODE` assertions; `build_celery_app` config; `dotted_path` round-trip; `HybridEventDispatcher` sync/background/mixed; `loop_runtime`/`container`/`tasks._dispatch` with fakes; settings loader tests.

**Integration (eager mode):** `task_always_eager=True` + `task_eager_propagates=True`, task registered via importing `app.main.worker.tasks` once, `get_worker_container()` pointed at the test's own FastAPI Dishka container via `set_worker_container()`/`clear_worker_container()` in an autouse fixture.

**Real-broker smoke test:** `tests/smoke/test_celery_broker.py` — real `Celery` producer (no eager mode) against the live `redis`+`worker` containers, asserts `AsyncResult(task_id).get(timeout=10).state == "SUCCESS"`.

**First-thing-to-verify (Step 4):** confirm `send_task(name, ...)` respects `task_always_eager` the same way `.delay()` does when the task is locally registered — expected Celery behavior, not confirmed in the public docs.

---

## Illustrative only — not built in this plan

```python
class OrderPlacedEvent(DomainEvent):
    order_id: OrderId
    customer_id: UserId
    total_amount: Decimal   # would need a new _ENCODERS/_DECODERS entry
    placed_at: datetime

class NotifyUserOrderRegistration:
    DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "sync"       # user needs confirmation now
    async def handle(self, event: OrderPlacedEvent) -> None: ...

class CreateInvoice:
    DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "background"  # can lag
    async def handle(self, event: OrderPlacedEvent) -> None: ...
```

`CreateInvoice` — DB-touching, background — is exactly the case that motivated building the persistent-loop worker design in Step 5 now rather than later.

---

## File Summary

| Action | File | Layer |
|---|---|---|
| MODIFY | `src/app/core/common/events/domain_event.py` | core |
| MODIFY | `src/app/core/common/ports/event_handler.py` | core |
| MODIFY | `src/app/core/common/events/handlers/send_welcome_email.py` | core |
| NEW | `src/app/outbound/adapters/celery_app.py` | outbound |
| NEW | `src/app/outbound/adapters/event_serialization.py` | outbound |
| NEW | `src/app/outbound/adapters/hybrid_event_dispatcher.py` | outbound |
| DELETE | `src/app/outbound/adapters/sync_event_dispatcher.py`, `background_event_dispatcher.py` | outbound |
| NEW | `src/app/main/worker/{__init__,loop_runtime,container,celery_app,tasks}.py` | main |
| MODIFY | `src/app/main/config/settings.py`, `loader.py`, `run.py` | main |
| MODIFY | `src/app/main/ioc/{core,outbound,provider_registry}.py` | main |
| MODIFY | `docker-compose.yml`, `docker-compose.test.yml`, `docker-entrypoint.sh`, `Makefile`, `pyproject.toml`, `env.example`/`.env` | infra |
| MODIFY | `README.md` | docs |
| NEW/MODIFY | ~13 unit test files, 1 integration conftest fixture, 1 smoke test | tests |

## Verification Plan

**Automated:**
```bash
make test            # unit, no infra
make test-docker      # integration (eager mode) + the real-broker smoke test, via docker
uv run lint-imports    # confirm no outbound -> main import was introduced
uv run mypy            # confirm every handler satisfies DISPATCH_MODE structurally
```

**Manual:**
1. `make upd` — brings up `app`, `db_pg`, `redis`, `worker`, `flower`, plus the existing observability stack.
2. `docker compose logs -f worker` — confirm it starts, connects to Redis, registers `app.events.dispatch_handler`.
3. Sign up a user via `POST /api/v1/account/signup/`; response returns immediately.
4. Check `docker compose logs worker` for the `SendWelcomeEmail` log lines, now running in the worker process.
5. Open `http://localhost:5555` (Flower) — confirm the signup's task appears as `SUCCESS`.
6. `make check` — full lint/type/import/test pass.

---

## Addendum — Celery-less deployment fallback (v0.7.1)

Added mid-implementation: a deployment built from this template should be able to skip Redis/Celery entirely (e.g. a cost-conscious cloud deployment) and still reliably run every handler, including ones declared `"background"` — just inline instead of via a queue, rather than erroring or silently dropping the event.

- **`CelerySettings.ENABLED: bool = True`** (env `CELERY_ENABLED`) — new field.
- **`HybridEventDispatcher`** gains a `celery_enabled: CeleryEnabled` constructor parameter (`CeleryEnabled = NewType("CeleryEnabled", bool)`, defined in `hybrid_event_dispatcher.py`, mirroring the existing `CookieName` pattern for wrapping a setting into a DI-resolvable type without `outbound` importing `app.main.config.settings`). `dispatch()`'s branch condition becomes `if handler.DISPATCH_MODE == "sync" or not self._celery_enabled:` — when Celery is disabled, *every* handler runs inline, regardless of its own declared mode.
- **`main/ioc/outbound.py`'s `CeleryProvider`** gains `provide_celery_enabled(self, celery: CelerySettings) -> CeleryEnabled`.
- **`docker-compose.yml`**: `redis`, `worker`, `flower` moved behind a `profiles: ["celery"]` gate (active by default via `COMPOSE_PROFILES=celery` in `env.example`); `app`'s `depends_on: redis` was removed, since `app` no longer strictly requires Redis to be reachable at startup.
- **`env.example`**: `CELERY_ENABLED=true` and `COMPOSE_PROFILES=celery` added, with a comment describing how to flip both for a Celery-less setup.

**Trade-off accepted:** without `app`'s `depends_on: redis`, there's a small startup race when Celery *is* enabled (a signup could theoretically arrive before `redis` finishes its healthcheck) — accepted in exchange for `redis`/`worker`/`flower` being cleanly skippable via profiles.

---

## Addendum — WorkerProvider, not a CoreProvider split (v0.7.2)

Found via the real `make test-docker` run (not something a unit test could have caught): the worker process crashed on every `worker_process_init` with `GraphMissingFactoryError` for `Request`. Excluding just `RequestProvider` from the worker's providers (the original Step 5/7 design) wasn't enough — `CoreProvider` unconditionally declares `current_user_service = provide(CurrentUserService)`, and Dishka validates the *entire* declared graph at container-build time, not just what's actually resolved. `CurrentUserService → IdentityProvider → AuthService → CookieManager → Request` is unsatisfiable without a real HTTP request, and `GrantAdmin` (confirmed) plus the other CQRS commands need `CurrentUserService` directly for authorization — so reusing `CoreProvider`/`AuthProvider` for the worker at all was the actual problem, not merely which pieces of them were included.

**The fix explicitly does *not* split or edit `CoreProvider`/`AuthProvider`/`outbound_providers()`.** Those are reverted to their exact original (pre-Celery) shape. Instead:
- **`src/app/main/worker/provider.py` (new)** — a wholly independent `WorkerProvider`, declaring only what registered event handlers actually need (currently: `EmailSender` + `SendWelcomeEmail`, duplicating `CoreProvider`'s `provide_email_sender` on purpose rather than sharing it), plus `get_worker_providers()` returning `(WorkerProvider(), HasherThreadPoolProvider(), PersistenceSqlaProvider())` — the latter two reused as-is since neither needs a `Request`.
- **`main/ioc/provider_registry.py`** — `get_worker_providers()` removed; `get_providers()` (web) now composes `CoreProvider(), *outbound_providers(), CeleryProvider()` directly, since `CeleryProvider` is only needed by the web side.
- **`main/worker/container.py`** — imports `get_worker_providers` from `app.main.worker.provider`; its settings context trimmed to just `PostgresSettings`/`SqlaSettings`/`PasswordHasherSettings`/`EmailSettings` (nothing Celery/Redis/auth-related, since none of that is in the worker's provider set anymore).

**Why this shape, not a `CoreProvider` split:** deleting `app/main/worker/` entirely now requires zero changes anywhere else — `CoreProvider`, `AuthProvider`, and `outbound_providers()` are back to exactly what the original template author wrote. A small amount of duplication (the email-sender wiring) was accepted deliberately in exchange for that isolation, rather than editing code whose full set of consumers wasn't independently verified.

---

## Addendum — `send_task()` ignores `task_always_eager` (v0.7.3)

Also found via `make test-docker`, after the `WorkerProvider` fix got the worker running cleanly: the eager-mode integration tests (`test_sign_up.py`, `test_create_user.py`) still failed with an empty `SpyEmailSender.sent`, alongside a Celery runtime warning: `AlwaysEagerIgnored: task_always_eager has no effect on send_task`. This is exactly the uncertainty Step 9 flagged and left unconfirmed ("verify with a throwaway script before relying on it") — now confirmed false. `Celery.send_task()` (by task name) does not honor `task_always_eager` at all; only `.apply_async()`/`.delay()` called on the actual bound `Task` object do. Since `send_task()` still went through to the real broker during the eager tests, the real `worker` container (also running, per the `test-docker-app` Makefile change) picked up the message and ran `SendWelcomeEmail` against *its own* `EmailSender` (from `WorkerProvider`) — never touching the test's `SpyEmailSender`.

**Fix, in `HybridEventDispatcher.dispatch()`'s background branch:** look up `self._celery_app.tasks.get(DISPATCH_HANDLER_TASK_NAME)` first. If found (only true when something deliberately points this dispatcher at the same Celery object the task is registered on — i.e. only in eager-mode tests), call `.apply_async(kwargs=...)` on that bound task, which does respect `task_always_eager`. Otherwise, fall back to the original `send_task(name, kwargs=...)` call — the production path, unchanged, since the web process's own Celery object (built independently by `CeleryProvider`) never has the task registered on it.

Also found via `make test-docker`: the worker's healthcheck failed intermittently under this sandbox's real CPU contention (4 cores, and Celery's own default `--concurrency` is one process per core, competing with `db_pg`/`redis`/the build itself during startup) — not a bug, but tightened `healthcheck.start_period` (to 45s, since `docker compose up --wait` treats the first "unhealthy" transition as a hard failure rather than polling to `--wait-timeout`) and added `CelerySettings.WORKER_CONCURRENCY: int = 2` (env `CELERY_WORKER_CONCURRENCY`), a deliberately modest default for this template's expected scale, wired into `docker-entrypoint.sh`'s `worker` command via `--concurrency`.

---

## Addendum — `COMPOSE_PROFILES` derived from `CELERY_ENABLED`, not set independently (v0.7.4)

Raised directly by the user while manually testing the Celery-less fallback: having both `CELERY_ENABLED` (application-level behavior) and `COMPOSE_PROFILES` (Compose-level service provisioning) as independently-settable was a real misconfiguration risk, not just redundant-looking — `CELERY_ENABLED=true` with `COMPOSE_PROFILES=` empty means the app *thinks* it can reach Redis and gets a real connection error the moment a background handler fires, since Redis was never started.

**Fix:** `scripts/makefile/docker_env.sh`/`local_env.sh` (which already generate `.env` from `env.example` + `.secrets`) now derive `COMPOSE_PROFILES` from whichever `CELERY_ENABLED` value is actually in effect, appending it last (`.env` parsing is last-value-wins) rather than leaving it as a static line in `env.example`. `CELERY_ENABLED` is now the only setting anyone sets directly; `COMPOSE_PROFILES` is a generated artifact. Also fixed in the same pass: `local_env.sh` was missing a `REDIS_HOST=127.0.0.1` rewrite (it already had one for `POSTGRES_HOST`) — without it, the app running locally (outside Docker) would have tried to resolve the Docker-internal `redis` hostname and failed.

---

## Addendum — Missing trailing newline in `.secrets` corrupted the generated `.env` (v0.7.5)

Found while manually verifying the v0.7.4 fix: setting `CELERY_ENABLED=false` as the last line of `.secrets` (a very ordinary way to edit that file, e.g. via `sed -i` or an editor that doesn't force a final newline) produced a corrupted `.env` — the derived `COMPOSE_PROFILES=` line landed on the *same* line as `CELERY_ENABLED=false`, yielding one malformed line (`CELERY_ENABLED=falseCOMPOSE_PROFILES=`) instead of two. Root cause: both scripts build `.env` with `cat .secrets` inside a `{ ... } > .env` block, then `>>`-append the derived `COMPOSE_PROFILES` line afterward — if `.secrets`' last line has no trailing newline, `cat` doesn't emit one, so the appended line concatenates onto it instead of starting a new line.

**Fix:** both `scripts/makefile/docker_env.sh` and `scripts/makefile/local_env.sh` now emit an unconditional `echo` immediately after `cat .secrets` (inside the `if [ -f .secrets ]` block), guaranteeing a newline terminator regardless of how `.secrets` itself was edited.

---

## Addendum — Redis Commander, for visibility into Redis itself (v0.7.6)

Raised directly by the user after manually verifying both the Celery-enabled and Celery-less paths worked: every other piece of this stack is visually inspectable (Adminer for Postgres, Flower for Celery's task-level view, Grafana/Loki for logs, Swagger for the API, coverage HTML for tests) except Redis itself — there was no way to actually look inside it and confirm what's really stored there (broker messages vs. result-backend entries), as opposed to trusting Flower's task-level abstraction over it.

**Fix:** a new `redis-commander` service (`rediscommander/redis-commander:latest`) added to `docker-compose.yml`, directly after `flower`, inside the same `profiles: ["celery"]` gate (so it's skipped automatically alongside `redis`/`worker`/`flower` whenever `CELERY_ENABLED=false`). `REDIS_HOSTS=broker:redis:6379:0,results:redis:6379:1` gives it two labeled connections in its UI — one per logical Redis database already in use (`REDIS_DB` for the Celery broker, `REDIS_RESULT_DB` for the result backend) — so both are browsable side by side. `env.example` gains `REDIS_COMMANDER_PORT=8081` (matching the existing `FLOWER_PORT` pattern), `Makefile`'s `open-dashboards` gets an `xdg-open` line for it, and `README.md`'s dashboard URL list and "Background Events" section both mention it.
