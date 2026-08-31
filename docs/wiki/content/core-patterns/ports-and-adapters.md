# Ports and Adapters (Repository Pattern)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/commands/ports/`](../../../../src/app/core/commands/ports/) — write-side ports (`Flusher`, `TransactionManager`, `UserTxStorage`, `UtcTimer`, `OutboxRepository`)
    - [`src/app/core/common/ports/`](../../../../src/app/core/common/ports/) — cross-cutting ports (`PasswordHasher`, `EmailSender`, `EventDispatcher`, `EventHandler`, `IdentityProvider`, `AccessRevoker`)
    - [`src/app/core/queries/ports/user_reader.py`](../../../../src/app/core/queries/ports/user_reader.py) — read-side port (`UserReader`)
    - [`src/app/outbound/adapters/`](../../../../src/app/outbound/adapters/) — concrete adapters for most of the above
    - [`src/app/outbound/auth_ctx/`](../../../../src/app/outbound/auth_ctx/) — a second, parallel set of session/auth adapters

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The idea in one sentence

`core` declares an interface for everything it needs from the outside world — hashing a password, sending an email, committing a transaction — and never imports the class that actually does the work. `outbound` provides that class. This is the **Dependency Inversion Principle**: instead of `core` depending on `outbound` (business rules depending on infrastructure details), both depend on an abstraction that `core` itself owns.

This overall shape — `core` owning abstract interfaces (**ports**) that `outbound` implements (**adapters**) — is what this page's title names directly: the **Ports and Adapters** pattern, also known as **Hexagonal Architecture** (coined by Alistair Cockburn). Where a port's specific job is fetching/storing domain objects while hiding the actual storage mechanism behind a collection-like interface — as `UserTxStorage`/`UserReader` do below — that particular shape is usually called the **Repository pattern**, the second name in this page's title.

!!! figure "Which way the dependency arrow points"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph coreLayer["core (innermost)"]
            useCase["SignUp / CreateUser"]
            port["PasswordHasher (Protocol)"]
        end
        subgraph outboundLayer["outbound"]
            adapter["BcryptPasswordHasher"]
        end
        subgraph mainLayer["main (composition root)"]
            wiring["CoreProvider.provide_password_hasher()"]
        end

        useCase -->|depends on the abstraction| port
        adapter -.->|implements| port
        wiring -->|injects the concrete class| useCase
        wiring --> adapter

        linkStyle default stroke-width:3px,stroke:#333333
        style coreLayer stroke-width:1px,stroke:#333333
        style outboundLayer stroke-width:1px,stroke:#333333
        style mainLayer stroke-width:1px,stroke:#333333
    ```

    > `useCase` never imports `BcryptPasswordHasher` — it only ever sees `PasswordHasher`. The dotted arrow points from the adapter *back* to the port it satisfies (structural typing — see below), while the solid dependency arrow from the use case only ever points at the port. `main` is the only layer that knows both sides exist and wires them together at startup; see [Dependency Injection with Dishka](dependency-injection.md) for exactly how.

## Ports are `Protocol`s, not ABCs (Abstract Base Classes) with `@abstractmethod` requiring inheritance

Every port in this codebase is a `typing.Protocol` with `@abstractmethod`-decorated methods (the decorator is inert on a `Protocol` — it exists as documentation and to satisfy some type-checker edge cases, not to enforce anything at runtime). A concrete adapter satisfies a port **structurally** — by having the right method signatures — not by explicitly subclassing it. Some adapters do subclass the port anyway (e.g. `class BcryptPasswordHasher(PasswordHasher):`) purely for readability/IDE (Integrated Development Environment) navigation; others don't (e.g. `AuthSqlaTransactionManager` in `outbound/auth_ctx/` implements `commit()` with the exact right shape but never imports `TransactionManager` at all). Both are equally valid to `mypy` — that's what "structural" means here.

## Every port, and its real adapter(s)

| Port (file) | Layer | Adapter(s) | What it's for |
|---|---|---|---|
| [`Flusher`](../../../../src/app/core/commands/ports/flusher.py) | commands | [`SqlaFlusher`](../../../../src/app/outbound/adapters/sqla_flusher.py) | Flush pending ORM (Object-Relational Mapping) changes mid-transaction, translating SQLAlchemy `IntegrityError`s into domain-specific exceptions (`UsernameAlreadyExistsError`, etc.) |
| [`TransactionManager`](../../../../src/app/core/commands/ports/transaction_manager.py) | commands | [`SqlaTransactionManager`](../../../../src/app/outbound/adapters/sqla_transaction_manager.py) (primary session), [`AuthSqlaTransactionManager`](../../../../src/app/outbound/auth_ctx/sqla_transaction_manager.py) (auth-session context) | Commit the unit of work — see [Transaction Management](transaction-management.md) |
| [`UserTxStorage`](../../../../src/app/core/commands/ports/user_tx_storage.py) | commands | [`SqlaUserTxStorage`](../../../../src/app/outbound/adapters/sqla_user_tx_storage.py) | Add/fetch a `User` by id within the write-side transaction |
| [`UtcTimer`](../../../../src/app/core/commands/ports/utc_timer.py) | commands | [`SystemUtcTimer`](../../../../src/app/outbound/adapters/system_utc_timer.py), [`AuthSessionUtcTimer`](../../../../src/app/outbound/auth_ctx/utc_timer.py) | The current time, in UTC (Coordinated Universal Time), injected rather than called via `datetime.now()` directly, so tests can fake it |
| [`OutboxRepository`](../../../../src/app/core/commands/ports/outbox_repository.py) | commands | [`SqlaOutboxRepository`](../../../../src/app/outbound/adapters/sqla_outbox_repository.py) | Write one transactional-outbox row (`add()` only — see [Domain Events & the Transactional Outbox](domain-events-outbox.md)) |
| [`PasswordHasher`](../../../../src/app/core/common/ports/password_hasher.py) | common | [`BcryptPasswordHasher`](../../../../src/app/outbound/adapters/bcrypt_password_hasher.py) | Hash/verify passwords (peppered + bcrypt, off the event loop via a thread pool) |
| [`EmailSender`](../../../../src/app/core/common/ports/email_sender.py) | common | [`ConsoleEmailSender`](../../../../src/app/outbound/adapters/console_email_sender.py) (dev, logs instead of sending), [`SmtpEmailSender`](../../../../src/app/outbound/adapters/smtp_email_sender.py) (real SMTP (Simple Mail Transfer Protocol)) | Send an email; which one is chosen is a runtime branch on `EmailSettings.USE_CONSOLE`, not two separate ports |
| [`EventDispatcher`](../../../../src/app/core/common/ports/event_dispatcher.py) | common | [`HybridEventDispatcher`](../../../../src/app/outbound/adapters/hybrid_event_dispatcher.py) | Route a domain event to its handlers, `"sync"` or `"background"` per handler — see [Domain Events & the Transactional Outbox](domain-events-outbox.md) |
| [`EventHandler[T]`](../../../../src/app/core/common/ports/event_handler.py) | common | [`SendWelcomeEmail`](../../../../src/app/core/common/events/handlers/send_welcome_email.py) (this one lives *in* `core`, not `outbound` — a handler is itself a piece of business logic, just one triggered by an event instead of an HTTP (HyperText Transfer Protocol) request) | Handle one event type; declares its own `DISPATCH_MODE` |
| [`IdentityProvider`](../../../../src/app/core/common/ports/identity_provider.py) | common | [`AuthSessionIdentityProvider`](../../../../src/app/outbound/adapters/auth_session_identity_provider.py) | Who is the current caller? (delegates to `AuthService`) |
| [`AccessRevoker`](../../../../src/app/core/common/ports/access_revoker.py) | common | [`AuthSessionAccessRevoker`](../../../../src/app/outbound/adapters/auth_session_access_revoker.py) | Revoke every session a user holds (used by admin deactivate/revoke-admin flows) |
| [`UserReader`](../../../../src/app/core/queries/ports/user_reader.py) | queries | [`SqlaUserReader`](../../../../src/app/outbound/adapters/sqla_user_reader.py) | Read-side listing/pagination/sorting — a raw `select()` returning a `TypedDict`, not an ORM-hydrated entity (queries don't need domain objects, just data) |

> Two ports above — `AuthSessionIdentityProvider` and `AuthSessionAccessRevoker` — are themselves thin adapters over a *third* internal component, `AuthService` (`src/app/outbound/auth_ctx/service.py`), which is not itself a port/adapter pair: it's a concrete session-management class with its own internal storage/transaction-manager/timer dependencies (`AuthSessionSqlaTxStorage`, `AuthSqlaTransactionManager`, `AuthSessionUtcTimer`), documented in its own model file as a candidate to become a fully separate **bounded context** later (see [Outbound Layer (Infrastructure Adapters)](../architecture/outbound-layer.md) for what that DDD term means and why `auth_ctx` is already shaped like one).

## Why `auth_ctx` has its own `SqlaTransactionManager` and `UtcTimer`

Notice `TransactionManager` and `UtcTimer` each have **two** adapters, not one. `src/app/outbound/auth_ctx/` is a separate mini vertical slice (session issuance/lookup/expiry) that touches its own `AsyncSession` (`AuthAsyncSession`, a distinct DI (Dependency Injection) type from the primary session — see [Dependency Injection with Dishka](dependency-injection.md)) and needed the exact same commit/now-time behavior as the primary write path. Rather than making the primary `SqlaTransactionManager`/`SystemUtcTimer` classes generic over which session they bind to, this codebase just wrote a second, small, nearly-identical class (`AuthSqlaTransactionManager`, `AuthSessionUtcTimer`) scoped to `auth_ctx`. A few lines of duplication in exchange for two fully independent, easy-to-reason-about classes — the same additive, non-shared-abstraction preference this codebase applies elsewhere (see [Dependency Injection with Dishka](dependency-injection.md)'s `WorkerProvider` section for another example of the same trade-off).

!!! figure "Two parallel adapter sets for the same two ports"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph ports["core ports"]
            tm["TransactionManager"]
            timer["UtcTimer"]
        end
        subgraph primary["outbound/adapters (primary session)"]
            sqlatm["SqlaTransactionManager"]
            systimer["SystemUtcTimer"]
        end
        subgraph auth["outbound/auth_ctx (auth session)"]
            authtm["AuthSqlaTransactionManager"]
            authtimer["AuthSessionUtcTimer"]
        end

        sqlatm -.-> tm
        systimer -.-> timer
        authtm -.->|structural only, no import of TransactionManager| tm
        authtimer -.->|structural only| timer

        linkStyle default stroke-width:3px,stroke:#333333
        style ports stroke-width:1px,stroke:#333333
        style primary stroke-width:1px,stroke:#333333
        style auth stroke-width:1px,stroke:#333333
    ```

    > The dotted lines from `auth_ctx`'s classes are structural, not a real import — `AuthSqlaTransactionManager` never imports `TransactionManager`. It's included in the diagram because Dishka resolves it *as* a `TransactionManager` wherever `SignUp`/`LogIn`/etc. depend on that port, exactly as if it had subclassed it.

## What this buys you, concretely

- **Swap infrastructure without touching business rules.** `EmailSender` has two adapters selected by one setting (`EmailSettings.USE_CONSOLE`) — `SendWelcomeEmail` (a use case) never changes.
- **Unit-test business rules with zero database or SMTP server.** Any port can be satisfied in a test by a hand-written fake or a `unittest.mock.Mock(spec=...)` — no container, no network call.
- **`core` never knows it's running behind HTTP, or that its data lives in Postgres.** `PasswordHasher`, `EventDispatcher`, `UserReader` — none of these say "SQL" (Structured Query Language) or "bcrypt" anywhere in `core`.

This is enforced, not just conventional: `import-linter`'s `layers` contract (`main → inbound → outbound → core`) fails CI (Continuous Integration) the moment `core` imports anything from `outbound`. See [Architecture → Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what that check does and doesn't catch.

## Where to go next

- [Dependency Injection with Dishka](dependency-injection.md) — how `main` actually wires each port to its concrete adapter at startup.
- [Transaction Management (Unit of Work-style)](transaction-management.md) — a deeper look at `Flusher`/`TransactionManager` and the commit boundary.
- [Domain Events & the Transactional Outbox](domain-events-outbox.md) — how `EventDispatcher`/`EventHandler`/`OutboxRepository` fit together.
