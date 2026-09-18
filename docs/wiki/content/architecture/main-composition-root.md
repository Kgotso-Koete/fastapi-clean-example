# Main (Composition Root)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/run.py`](../../../../src/app/main/run.py) — `make_app()`, the web process's entry point
    - [`src/app/main/setup.py`](../../../../src/app/main/setup.py) — logging, middleware, metrics, exception-handler setup
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — `CoreProvider`, wiring every `core` port to a concrete `outbound` adapter
    - [`src/app/main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py) — `HasherThreadPoolProvider`, `PersistenceSqlaProvider`, `AuthProvider`, `CeleryProvider`
    - [`src/app/main/ioc/provider_registry.py`](../../../../src/app/main/ioc/provider_registry.py) — `get_providers()`, the web process's full provider list
    - [`src/app/main/config/`](../../../../src/app/main/config/) — settings models and their loaders
    - [`src/app/main/worker/`](../../../../src/app/main/worker/) — the Celery worker process's own, independent composition root
    - [`src/app/main/cli/`](../../../../src/app/main/cli/) — the CLI's own, independent composition root (see [CLI (Terminal Adapter)](../core-patterns/inbound-cli.md))
    - [`src/app/main/ioc/public_api.py`](../../../../src/app/main/ioc/public_api.py) / [`src/app/main/run_public_api.py`](../../../../src/app/main/run_public_api.py) — the public API's own, independent composition root, mounted into the *same* OS process as the web app (see [Public API (Server-to-Server Clients)](../core-patterns/public-api.md))
    - [`src/app/main/celery_factory.py`](../../../../src/app/main/celery_factory.py) — `build_celery_app()`, shared by both Celery-aware processes

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What lives here

`main` is the outermost layer and the only one allowed to import all three of the others (per [Layer Dependencies & Import Rules](layer-dependencies.md)). It's where every concrete decision actually gets made: which `outbound` adapter satisfies which `core` port, what settings come from which environment variables, and how the FastAPI app itself gets assembled. Nothing under `src/app/main/` is imported by `core`, `outbound`, or `inbound` — it only ever imports *them*.

## Four composition roots, three OS processes

This codebase actually has **four independent composition roots** — `main/run.py`'s `make_app()` (the private, cookie-authenticated web app), `main/ioc/public_api.py`'s `PublicApiProvider` (the API-key-authenticated public API), `main/worker/` (the Celery worker), and `main/cli/` (the terminal adapter) — spread across only **three OS (Operating System) processes**. The public API is the one surprise: it does **not** get its own process the way the worker and the CLI invocation do. `docker-entrypoint.sh` boots exactly one `uvicorn` process running `make_app_with_public_api()`, which mounts the public API as a nested Starlette sub-application (its own Dishka container, its own `setup_dishka()` call) inside the *same* process as the private app. See [Dependency Injection with Dishka](../core-patterns/dependency-injection.md) for exactly why that container still has to be independent (Dishka validates a whole graph at build time, and `IdentityProvider`/`AccessRevoker` bind to different concrete adapters in each) even though it shares a process with `CoreProvider`'s own container.

Every composition root builds its own Dishka container from its own provider list, and none of them ever shares a live Python object with another — they only agree on shared contracts (the `"app.events.dispatch_handler"` Celery task name, and the one Postgres database all four connect to).

!!! figure "Four composition roots: web process (two containers), worker process, CLI process"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph webproc["web OS process — main/run_public_api.py: make_app_with_public_api()"]
            subgraph web["private app — make_app()"]
                core_p["CoreProvider\n(CQRS commands/queries)"]
                outbound_p["outbound_providers()\n(hasher pool, persistence, auth)"]
                celery_p["CeleryProvider\n(CeleryEnabled flag only)"]
            end
            subgraph pub["public API — make_public_api_app() (/public)"]
                pub_p["PublicApiProvider\n(API-key issue/list/revoke, usage, profile)"]
            end
        end

        subgraph worker["worker OS process — main/worker/"]
            worker_p["WorkerProvider\n(email sender, outbox repo, handlers)"]
            outbound_reuse["HasherThreadPoolProvider\nPersistenceSqlaProvider\n(reused as-is)"]
        end

        subgraph cliproc["CLI OS process — main/cli/ (one per invocation)"]
            cli_p["CliProvider\n(admin/ops terminal commands)"]
        end

        db[("Postgres")]
        redis[("Redis / Celery broker")]

        core_p --> db
        outbound_p --> db
        pub_p --> db
        worker_p --> db
        outbound_reuse --> db
        cli_p --> db
        celery_p -.->|CeleryEnabled flag| redis
        worker_p -->|drains outbox, sends tasks| redis

        linkStyle default stroke-width:3px,stroke:#333333
        style webproc stroke-width:1px,stroke:#333333
        style web stroke-width:1px,stroke:#333333
        style pub stroke-width:1px,stroke:#333333
        style worker stroke-width:1px,stroke:#333333
        style cliproc stroke-width:1px,stroke:#333333
    ```

    > All four ultimately talk to the same Postgres database (and the worker/web talk to the same Redis broker too), but each builds its own, independently-validated Dishka container: the private app's via [`get_providers()`](../../../../src/app/main/ioc/provider_registry.py), the public API's via [`get_public_api_providers()`](../../../../src/app/main/ioc/public_api.py) (both called from `main/run_public_api.py`, in the one web process), the worker's via [`get_worker_providers()`](../../../../src/app/main/worker/provider.py) (its own process), and the CLI's via [`CliProvider`](../../../../src/app/main/cli/provider.py) (a new, short-lived process per invocation).

## The web process: `make_app()`

[`run.py`](../../../../src/app/main/run.py)'s `make_app()` builds the private app on its own, and is still what tests and the app's own `if __name__ == "__main__":` block call directly. The actual process entry point `docker-entrypoint.sh` boots, though, is `main/run_public_api.py`'s `make_app_with_public_api()` — it calls this same `make_app()` unmodified, then mounts the public API sub-app on top (see [Public API (Server-to-Server Clients)](../core-patterns/public-api.md)). Either way, building the private app itself proceeds identically: it loads every settings model (via `main/config/loader.py`'s `load_*_settings()` functions, each reading from environment variables through `pydantic-settings`), constructs the `FastAPI` instance (with `docs_url`/`redoc_url` set to `None` outside `ENVIRONMENT=development` — see [Environment-aware deployment gating](../configuration/deployment-environments.md)), builds the Dishka container from `get_providers()` plus a `context={...}` dict binding every settings object by type, and finally calls `setup_middlewares()`/`setup_metrics()`/`setup_global_exception_handlers()` (all in [`setup.py`](../../../../src/app/main/setup.py)) before mounting the root router from [`inbound`](inbound-layer.md).

`get_providers()` (in [`provider_registry.py`](../../../../src/app/main/ioc/provider_registry.py)) is short and literal:

```python
def get_providers() -> Iterable[Provider]:
    return (
        CoreProvider(),
        *outbound_providers(),
        CeleryProvider(),
    )
```

`CoreProvider` (in [`ioc/core.py`](../../../../src/app/main/ioc/core.py)) is where every `core` port meets its concrete adapter — this is the single file to read to answer "what actually implements `PasswordHasher`" or "what implements `TransactionManager`" for the web process:

```python
identity_provider = provide(AuthSessionIdentityProvider, provides=IdentityProvider)
authz_user_finder = provide(SqlaUserTxStorage, provides=AuthzUserFinder)
access_revoker = provide(AuthSessionAccessRevoker, provides=AccessRevoker)

utc_timer = provide(SystemUtcTimer, provides=UtcTimer)
user_tx_storage = provide(SqlaUserTxStorage, provides=UserTxStorage)
flusher = provide(SqlaFlusher, provides=Flusher)
tx_manager = provide(SqlaTransactionManager, provides=TransactionManager)
outbox_repository = provide(SqlaOutboxRepository, provides=OutboxRepository)
```

`outbound_providers()` (in [`ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py)) returns `HasherThreadPoolProvider`, `PersistenceSqlaProvider`, `AuthProvider`, and `RequestProvider` — the DB (database) engine/session factory, the bcrypt thread pool and semaphore, every `auth_ctx` class (`AuthService`, `CookieManager`, `JwtProcessor`, the `SignUp`/`LogIn`/`LogOut`/`ChangePassword` handlers), and a `from_context(provides=Request)` binding that makes the current Starlette `Request` injectable — which is exactly what `CookieManager` needs, and exactly what the worker process's providers deliberately never declare.

## The worker process: a second, independent provider

[`worker/provider.py`](../../../../src/app/main/worker/provider.py)'s `WorkerProvider` is its own class — not a subset or a split of `CoreProvider`. Its docstring states the reasoning directly:

```python
class WorkerProvider(Provider):
    """
    Declares exactly what the registered event handlers need to run in a
    Celery worker process -- nothing more. Deliberately independent of
    CoreProvider/AuthProvider (the web process's providers), rather than
    reusing or splitting them: CoreProvider's CQRS commands need
    CurrentUserService, which needs a real Starlette Request through
    AuthService/CookieManager -- something a worker process fundamentally
    doesn't have. Dishka validates every declared provider's dependencies
    at container-build time, regardless of whether anything ever actually
    resolves them, so simply omitting a Request provider isn't enough --
    the worker's container must never declare anything that needs one.

    This does duplicate the email_sender wiring already in CoreProvider
    (see main/ioc/core.py) rather than share it. That's intentional: it
    keeps this class -- and the whole app.main.worker package -- a
    self-contained addition. Deleting this file and app.main.worker
    entirely would not require touching CoreProvider, AuthProvider, or any
    other pre-existing wiring.
    """
```

Concretely, `WorkerProvider` re-declares its own `provide_email_sender` (identical branching logic to `CoreProvider`'s own, duplicated rather than imported or refactored out into a shared base), and provides `SendWelcomeEmail` and `SqlaOutboxRepository` at `Scope.REQUEST`. `get_worker_providers()` combines it with `HasherThreadPoolProvider` and `PersistenceSqlaProvider` reused as-is from `main/ioc/outbound.py` (neither needs a `Request`, so both validate fine in the worker's container too) — but deliberately excludes `AuthProvider`, `RequestProvider`, and `CeleryProvider` entirely, since the worker never handles an HTTP (HyperText Transfer Protocol) request and never dispatches events itself; it only ever executes one handler at a time, resolved by dotted path (see [`worker/tasks.py`](../../../../src/app/main/worker/tasks.py)'s `_dispatch()`).

This is the same additive, non-invasive pattern used everywhere else event dispatch was added to this codebase: rather than reshaping `CoreProvider` to serve two different process types, the worker gets its own small, self-contained provider that could be deleted along with the rest of `app.main.worker` without requiring a single line of `CoreProvider` or `AuthProvider` to change.

## What each process actually starts

The web process's entry point is a single `FastAPI` app built once, at import/startup time, by `uvicorn`. The worker process is more involved: [`worker/celery_app.py`](../../../../src/app/main/worker/celery_app.py) builds the module-level `celery_app` object at *import* time (Celery's CLI (Command-Line Interface) needs a real object the moment the module loads, before any event loop or container exists), then registers `worker_process_init`/`worker_process_shutdown` signal handlers that, per worker subprocess, call `map_tables()`, start a persistent background event loop ([`worker/loop_runtime.py`](../../../../src/app/main/worker/loop_runtime.py)), build that process's Dishka container on that same loop, and start the outbox drain loop ([`worker/outbox_drain_loop.py`](../../../../src/app/main/worker/outbox_drain_loop.py)) — a plain polling coroutine, not a Celery Beat task, for reasons documented in its own module (avoiding a heartbeat task cluttering Flower's live event stream). `celery_factory.py`'s `build_celery_app()` is the one function both processes call to actually construct a `Celery` object — taking plain values rather than a settings blob, so it stays independent of which process, or which concrete settings model, is calling it.

## Where to go next

- [Dependency Injection with Dishka](../core-patterns/dependency-injection.md) — the full container-per-composition-root model, all four roots, and exactly why the public API needs its own container despite sharing a process with the private app.
- [Public API (Server-to-Server Clients)](../core-patterns/public-api.md) — `PublicApiProvider`'s own composition root in detail.
- [CLI (Terminal Adapter)](../core-patterns/inbound-cli.md) — `CliProvider`'s own composition root in detail, and why it lives under `main/cli/` rather than `inbound/cli/`.
- [Layer Dependencies & Import Rules](layer-dependencies.md) — why `main` is the only layer allowed to import all three of the others.
- [Outbound Layer (Infrastructure Adapters)](outbound-layer.md) — every concrete adapter `CoreProvider`/`WorkerProvider` wire in above.
- [Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) — the full mechanism the worker process's outbox drain loop and `dispatch_event_handler_task` implement.
