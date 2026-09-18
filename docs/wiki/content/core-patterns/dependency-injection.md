# Dependency Injection with Dishka

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — `CoreProvider`: use cases, queries, and most core ports
    - [`src/app/main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py) — `HasherThreadPoolProvider`, `PersistenceSqlaProvider`, `AuthProvider`, `CeleryProvider`, `RequestProvider`
    - [`src/app/main/ioc/provider_registry.py`](../../../../src/app/main/ioc/provider_registry.py) — `get_providers()`, the single list the private app builds its container from
    - [`src/app/main/ioc/public_api.py`](../../../../src/app/main/ioc/public_api.py) — `PublicApiProvider` + `get_public_api_providers()`, the public API's own, independent provider list — mounted into the **same OS process** as the private app, unlike the worker below
    - [`src/app/main/worker/provider.py`](../../../../src/app/main/worker/provider.py) — `WorkerProvider` + `get_worker_providers()`, the Celery worker's own, independent provider list, in its own separate OS process

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What Dishka is doing here

[Dishka](https://github.com/reagento/dishka) is this project's dependency-injection container. A **`Provider`** is a class that declares how to build one or more types; a **container**, built from a list of providers, resolves a requested type by finding the provider that declares it and recursively resolving whatever *that* provider's constructor needs. `main` is the only layer that ever imports both a port (from `core`) and its adapter (from `outbound`) in the same file — that's what makes it the composition root: the one place the wiring decision actually gets made. See [Ports and Adapters](ports-and-adapters.md) for the port/adapter pairs themselves.

## Three containers, but only two OS processes

This codebase builds **three independent Dishka containers**, from three different provider lists — but only **two independent OS (Operating System) processes**. The private app and the public API run as two separate containers inside the *same* `uvicorn` process; only the Celery worker is a genuinely separate process.

!!! figure "Three composition roots, two OS processes"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph web["Web OS process (app.main.run_public_api)"]
            subgraph webApp["Private app -- make_app()"]
                getProviders["get_providers()"]
                core["CoreProvider"]
                outbound["outbound_providers():<br/>HasherThreadPoolProvider<br/>PersistenceSqlaProvider<br/>AuthProvider<br/>RequestProvider"]
                celery["CeleryProvider"]
                webContainer[("AsyncContainer #1")]
            end
            subgraph pubApp["Public app -- make_public_api_app() (mounted at /public)"]
                getPublicProviders["get_public_api_providers()"]
                pubP["PublicApiProvider"]
                sharedC["HasherThreadPoolProvider"]
                sharedD["PersistenceSqlaProvider"]
                pubR["RequestProvider"]
                pubContainer[("AsyncContainer #2")]
            end
        end
        subgraph workerProc["Worker OS process (app.main.worker)"]
            getWorkerProviders["get_worker_providers()"]
            workerP["WorkerProvider"]
            sharedA["HasherThreadPoolProvider"]
            sharedB["PersistenceSqlaProvider"]
            workerContainer[("AsyncContainer #3")]
        end

        getProviders --> core --> webContainer
        getProviders --> outbound --> webContainer
        getProviders --> celery --> webContainer

        getPublicProviders --> pubP --> pubContainer
        getPublicProviders --> sharedC --> pubContainer
        getPublicProviders --> sharedD --> pubContainer
        getPublicProviders --> pubR --> pubContainer

        getWorkerProviders --> workerP --> workerContainer
        getWorkerProviders --> sharedA --> workerContainer
        getWorkerProviders --> sharedB --> workerContainer

        linkStyle default stroke-width:3px,stroke:#333333
        style web stroke-width:1px,stroke:#333333
        style webApp stroke-width:1px,stroke:#333333
        style pubApp stroke-width:1px,stroke:#333333
        style workerProc stroke-width:1px,stroke:#333333
    ```

    > `HasherThreadPoolProvider` and `PersistenceSqlaProvider` (both declared in `main/ioc/outbound.py`) are the only providers genuinely reused across lists — reused because, as their own docstrings establish, neither one depends on a Starlette `Request`. `RequestProvider` *is* needed by both apps in the web process (each resolves its own `IdentityProvider`, and the public one reads the `X-API-Key` header straight off a real `Request`), but is meaningless to the worker, which has no HTTP request at all — see below. Everything else is either private-app-only (`CoreProvider`, `AuthProvider`, `CeleryProvider`), public-API-only (`PublicApiProvider`), or worker-only (`WorkerProvider`).

## Why the public API isn't just "one more router" on the existing app

`PublicApiProvider` and `CoreProvider` both bind `IdentityProvider` and `AccessRevoker` — but to *different* concrete adapters: `CoreProvider` to `AuthSessionIdentityProvider`/`AuthSessionAccessRevoker` (cookie sessions), `PublicApiProvider` to `ApiKeyIdentityProvider`/`ApiKeyAccessRevoker` (API keys). Dishka validates a container's *entire* dependency graph at build time, and does not allow two different concrete bindings for the same abstract port to coexist in one container — so these two provider sets cannot simply be merged into one, the way you might add a second router with different auth middleware onto one Express `app` and call it done.

The fix is the same shape `WorkerProvider` already used for a genuinely separate process, just applied one level shallower: a wholly independent provider list, its own `AsyncContainer`, built and attached via its own `setup_dishka()` call — except here, both containers still end up served by the *same* running `uvicorn` process, because `make_app_with_public_api()` mounts the public API as a nested Starlette sub-application (`app.mount("/public", public_app)`) rather than launching it separately. One process, one port, two independent containers underneath. See [Public API (Server-to-Server Clients)](public-api.md) for the full design, including the endpoints this container actually serves and why a handful of use cases were deliberately *not* made available on it.

## Scopes: `Scope.APP` vs `Scope.REQUEST`

Every provider declares a `scope` — how long a value it builds should live:

- **`Scope.APP`** — built once, lives for the whole process. Used for things expensive to create or meant to be shared: the SQLAlchemy `AsyncEngine`, the bcrypt thread pool/semaphore, `UserService`, `JwtProcessor`, `AuthSessionUtcTimer`.
- **`Scope.REQUEST`** — built fresh per HTTP (HyperText Transfer Protocol) request (web) or per task (worker), and disposed at the end of it. Used for anything tied to one **unit of work** (see [Transaction Management](transaction-management.md) for what that means concretely): the `AsyncSession` itself, `CoreProvider`'s use cases (`CreateUser`, `GrantAdmin`, ...), `CurrentUserService`.

`CoreProvider.scope = Scope.REQUEST` is the class-level default; individual members override it with `@provide(scope=Scope.APP)` where a longer lifetime is correct (e.g. `provide_password_hasher`, `user_service`). `PersistenceSqlaProvider.provide_async_engine`/`provide_async_session_factory` are `Scope.APP` (one engine, one pooled sessionmaker for the process), while `provide_primary_async_session`/`provide_auth_async_session` are `Scope.REQUEST` — a fresh `AsyncSession` per request, opened and closed via an `async with` block so it's guaranteed closed even if the request raises.

## Two `AsyncSession` types from one factory, disambiguated by `NewType`

`PersistenceSqlaProvider` provides **two** `Scope.REQUEST` async sessions from the same `async_session_factory`: the plain `AsyncSession` (used by `SqlaUserTxStorage`, `SqlaFlusher`, `SqlaTransactionManager`, `SqlaOutboxRepository`, ...) and `AuthAsyncSession` (a `NewType` over `AsyncSession`, used only by `auth_ctx`'s own `AuthSessionSqlaTxStorage`/`AuthSqlaTransactionManager`). Dishka resolves by type, so without the `NewType` wrapper it couldn't tell the two providers apart — they're genuinely two separate database sessions open at once per request, one for the account-model write path and one for the session/auth write path, each independently committed. `CookieName` (`outbound/auth_ctx/cookie_manager.py`) and `CeleryEnabled` (`outbound/adapters/hybrid_event_dispatcher.py`) use the same `NewType`-wrapping trick for a different reason: `outbound` may not import `app.main.config.settings` directly (an `import-linter` contract, with `alembic/env.py` as the one explicit, non-precedent exception), so a plain `str`/`bool` setting value gets wrapped into a distinct type in `outbound` itself, and only `main`'s providers (`AuthProvider.provide_cookie_name`, `CeleryProvider.provide_celery_enabled`) are allowed to read the real `Settings` object and produce one.

## The `Request` provider, and why the worker cannot reuse `CoreProvider`

`RequestProvider` (`main/ioc/outbound.py`) does one thing: `request = from_context(provides=Request, scope=Scope.REQUEST)` — it hands Dishka's own per-request context object back out as a resolvable `Request` (Starlette's), which `CookieManager` (and transitively `AuthService` → `IdentityProvider` → `CurrentUserService`) depends on.

A Celery worker process has no HTTP request at all — there is no `Request` object to hand out, ever. This is exactly why `app.main.worker` builds its own `WorkerProvider` and its own `get_worker_providers()` instead of reusing (or trimming) `CoreProvider`/`AuthProvider`: Dishka validates a container's *entire declared dependency graph* at build time, not just the parts something actually resolves. `CoreProvider` unconditionally declares `current_user_service = provide(CurrentUserService)`, and `CurrentUserService → IdentityProvider → AuthService → CookieManager → Request` is unsatisfiable with no `Request` provider in scope — so simply omitting `RequestProvider` from the worker's list isn't enough; the worker's container must never declare anything that *chains* to needing one. This was found the hard way, via a real `make test-docker` run raising `GraphMissingFactoryError` for `Request` — not something a unit test alone could have caught, since unit tests don't build the real container.

!!! figure "Why WorkerProvider exists instead of a trimmed-down CoreProvider"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        cus["CurrentUserService"] --> idp["IdentityProvider"]
        idp --> authsvc["AuthService"]
        authsvc --> cm["CookieManager"]
        cm --> req["Request (Starlette)"]
        req -.->|only ever exists in the web process| webonly["Scope.REQUEST HTTP context"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `CoreProvider` declares `current_user_service` unconditionally, so any container built from `CoreProvider` must be able to satisfy every node in this chain, including `Request` — regardless of whether a given code path ever actually calls `CurrentUserService`. The worker never has a `Request`, so it cannot use `CoreProvider` at all, not even partially.

## `WorkerProvider`: a wholly independent, deliberately duplicated provider

`WorkerProvider` (`src/app/main/worker/provider.py`) declares only what registered event handlers actually need to run in a Celery worker process: `EmailSender` (for `SendWelcomeEmail`) and `SqlaOutboxRepository` (bound by its own concrete type, not the `OutboxRepository` Protocol, since the worker's drain loop calls `get_pending()`/`mark_processed()`/`delete()`/`commit()` — methods that exist on the concrete class but aren't part of the core port; see [Domain Events & the Transactional Outbox](domain-events-outbox.md)). Its `provide_email_sender` method is **line-for-line identical** to `CoreProvider.provide_email_sender` — copied, not shared, on purpose:

> "This does duplicate the email_sender wiring already in CoreProvider... That's intentional: it keeps this class — and the whole `app.main.worker` package — a self-contained addition. Deleting this file and `app.main.worker` entirely would not require touching `CoreProvider`, `AuthProvider`, or any other pre-existing wiring." — `WorkerProvider`'s own docstring

This is the codebase's additive-building-blocks principle applied directly to DI (Dependency Injection) wiring: a small amount of duplicated code (one `provide_email_sender` method) was accepted deliberately, in exchange for `CoreProvider`/`AuthProvider`/`outbound_providers()` staying **completely untouched** — reverted to their exact pre-Celery shape after an earlier attempt tried splitting `CoreProvider` instead and found it required touching code whose full set of consumers (every CQRS (Command Query Responsibility Segregation) command needing `CurrentUserService` for authorization) hadn't been independently verified. (CQRS here is the `core.commands`/`core.queries` write/read split — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for the enforced contract behind it.)

`get_worker_providers()` returns `(WorkerProvider(), HasherThreadPoolProvider(), PersistenceSqlaProvider())` — the latter two reused as-is, since neither needs a `Request`. `AuthProvider`, `RequestProvider`, and `CeleryProvider` are excluded entirely: the worker never dispatches events itself, it only executes one handler, resolved directly from a dotted path string carried in the Celery task payload (see [Domain Events & the Transactional Outbox](domain-events-outbox.md)).

## Where each container actually gets built

- **Private app**: `provider_registry.get_providers()` returns `(CoreProvider(), *outbound_providers(), CeleryProvider())`; `make_app()` builds the real `AsyncContainer` from this list once at startup, and Dishka's Starlette integration opens/closes a `Scope.REQUEST` child container per incoming HTTP request automatically.
- **Public API**: `public_api.get_public_api_providers()` returns `(PublicApiProvider(), HasherThreadPoolProvider(), PersistenceSqlaProvider(), RequestProvider())`; `make_public_api_app()` builds its *own* `AsyncContainer` from this list, and `make_app_with_public_api()` is what actually mounts that app (with its container already attached) onto the private app's `/public` path — both containers then live for as long as the one `uvicorn` process does.
- **Worker**: `app.main.worker.container.build_worker_container()` builds the `AsyncContainer` from `get_worker_providers()`, called from `celery_app.py`'s `worker_process_init` signal handler — once per worker OS process, on that process's own persistent event loop (see [Domain Events & the Transactional Outbox](domain-events-outbox.md) for why the loop has to be persistent). `app.main.worker.tasks` then opens one `Scope.REQUEST` child container per task, mirroring how the web side opens one per HTTP request.

## Where to go next

- [Public API (Server-to-Server Clients)](public-api.md) — what the second, API-key-authenticated container actually serves, and the deliberate scope boundary drawn around it.
- [Ports and Adapters (Repository Pattern)](ports-and-adapters.md) — the port/adapter pairs these providers actually wire together.
- [Domain Events & the Transactional Outbox](domain-events-outbox.md) — why the worker needs its own container and event loop at all.
- [Architecture → Main (Composition Root)](../architecture/main-composition-root.md) — the broader role `main` plays as the outermost layer.
