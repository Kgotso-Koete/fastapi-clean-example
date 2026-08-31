# Transaction Management (Unit of Work-style)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/commands/ports/transaction_manager.py`](../../../../src/app/core/commands/ports/transaction_manager.py) — the `TransactionManager` port
    - [`src/app/core/commands/ports/flusher.py`](../../../../src/app/core/commands/ports/flusher.py) — the `Flusher` port
    - [`src/app/outbound/adapters/sqla_transaction_manager.py`](../../../../src/app/outbound/adapters/sqla_transaction_manager.py) — `SqlaTransactionManager`
    - [`src/app/outbound/adapters/sqla_flusher.py`](../../../../src/app/outbound/adapters/sqla_flusher.py) — `SqlaFlusher`
    - [`src/app/outbound/auth_ctx/sqla_transaction_manager.py`](../../../../src/app/outbound/auth_ctx/sqla_transaction_manager.py) — `AuthSqlaTransactionManager`, the parallel adapter for the auth-session context
    - [`src/app/outbound/auth_ctx/handlers/sign_up.py`](../../../../src/app/outbound/auth_ctx/handlers/sign_up.py) and [`src/app/core/commands/create_user.py`](../../../../src/app/core/commands/create_user.py) — the two call sites that follow this exact commit-boundary pattern

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The pattern: `Flusher` + `TransactionManager` as a Unit of Work

A "Unit of Work" is a pattern for tracking everything one business operation changes and committing it — or none of it — as a single atomic step. This codebase doesn't have one class named `UnitOfWork`; instead it splits the same responsibility into two small ports, both satisfied by the same underlying SQLAlchemy `AsyncSession`:

- [`Flusher`](../../../../src/app/core/commands/ports/flusher.py) — `flush()`: pushes pending ORM (Object-Relational Mapping) changes to the database *within* the still-open transaction, so constraints (unique username, unique email, ...) get checked and any violation raises immediately, before anything commits.
- [`TransactionManager`](../../../../src/app/core/commands/ports/transaction_manager.py) — `commit()`: the actual commit boundary. Its own docstring calls it out directly (using **UoW** as shorthand for the Unit of Work pattern just described above): *"UoW-compatible interface for committing a business transaction... may be extended with rollback support."*

Both are plain `Protocol`s in `core` — a use case depends on the abstraction, never on `AsyncSession` or SQLAlchemy directly. See [Ports and Adapters](ports-and-adapters.md) for the general pattern these two ports are an instance of.

## `SqlaFlusher`: turning a generic DB error into a domain-specific one

[`SqlaFlusher.flush()`](../../../../src/app/outbound/adapters/sqla_flusher.py) wraps `AsyncSession.flush()` and, on an `IntegrityError`, inspects the error message for a known Postgres constraint name (`cn.UQ_USERS_USERNAME`, `cn.UQ_USERS_EMAIL`, `cn.UQ_USERS_PHONE_NUMBER`) via `CONSTRAINT_TO_ERROR`, re-raising the matching domain exception (`UsernameAlreadyExistsError`, etc.) instead of leaking a raw SQLAlchemy exception into `core`. Any other `SQLAlchemyError` becomes a generic `StorageError`. This is the concrete mechanism that lets a use case like `SignUp` write `except UsernameAlreadyExistsError: raise` — a plain domain exception, not a database-shaped one.

## `SqlaTransactionManager.commit()`

[`SqlaTransactionManager`](../../../../src/app/outbound/adapters/sqla_transaction_manager.py) is a thin wrapper: `await self._session.commit()`, with any `SQLAlchemyError` becoming `StorageError`. It holds no other state — the `AsyncSession` itself (injected, `Scope.REQUEST`-lived — see [Dependency Injection with Dishka](dependency-injection.md)) is the actual unit of work; `SqlaTransactionManager` just exposes the one operation `core` is allowed to trigger on it.

## A typical command flow, end to end

Both call sites that follow this pattern (`SignUp.execute()` and `CreateUser.execute()`) do the identical sequence: add the entity to storage, **stage** any events for background dispatch, flush, commit, then **dispatch** the events that are left. The `stage()`/`dispatch()` split exists specifically so a "background" handler's outbox row commits atomically with the domain change — see [Domain Events & the Transactional Outbox](domain-events-outbox.md) for why that matters; this page focuses on the commit boundary itself.

!!! figure "SignUp.execute(): flusher, transaction manager, and the commit boundary"
    ```mermaid
    sequenceDiagram
        autonumber
        participant UseCase as SignUp.execute()
        participant Entity as User (Entity)
        participant TxStorage as UserTxStorage
        participant Dispatcher as EventDispatcher
        participant Flusher as Flusher
        participant TxManager as TransactionManager
        participant DB as Postgres (AsyncSession)

        UseCase->>Entity: UserService creates User,<br/>records UserRegisteredEvent (in memory)
        UseCase->>TxStorage: add(user)
        TxStorage->>DB: session.add(user)
        UseCase->>Entity: collect_events()
        UseCase->>Dispatcher: stage(events)
        Dispatcher->>DB: outbox row added to the SAME session
        UseCase->>Flusher: flush()
        Flusher->>DB: session.flush()
        alt constraint violation
            DB-->>Flusher: IntegrityError
            Flusher-->>UseCase: UsernameAlreadyExistsError (re-raised)
            note over UseCase,DB: nothing committed -- transaction rolls back
        else flush succeeds
            Flusher-->>UseCase: (no error)
            UseCase->>TxManager: commit()
            TxManager->>DB: session.commit()
            note over DB: user row + outbox row commit together, or not at all
            UseCase->>Dispatcher: dispatch(events)
            Dispatcher->>Dispatcher: run "sync" handlers inline now
        end
    ```

    > What this shows: `flush()` is the checkpoint where constraint violations surface — while the transaction is still open, so a violation there means nothing commits at all. `commit()` is the one moment the transaction actually closes. Everything the entity added to the session before `commit()` — the `User` row and (per [Domain Events & the Transactional Outbox](domain-events-outbox.md)) the outbox row — becomes durable together, or neither does, because they share the same `AsyncSession` and thus the same Postgres transaction. `dispatch()`, deliberately, is the one step in this sequence that runs *after* commit — so it operates only on effects (sync handlers, or the Celery-disabled inline fallback) that don't need the atomicity guarantee the outbox already provides for background ones.

## Two sessions, two transaction managers, one request

The auth/session write path (issuing a session on login, expiring/refreshing it) is a second, independent unit of work against a **second** `AsyncSession` (`AuthAsyncSession`, a distinct DI (Dependency Injection)-resolvable type — see [Dependency Injection with Dishka](dependency-injection.md)), committed through its own adapter, [`AuthSqlaTransactionManager`](../../../../src/app/outbound/auth_ctx/sqla_transaction_manager.py) — structurally identical to `SqlaTransactionManager`, but never importing the `TransactionManager` Protocol at all (see [Ports and Adapters](ports-and-adapters.md) for why that's still valid). `AuthService.issue_session()` calls its own storage's `add()` then its own transaction manager's `commit()`, entirely independently of whatever the primary `AsyncSession`/`TransactionManager` pair is doing in the same request. A single HTTP (HyperText Transfer Protocol) request (e.g. `SignUp`, which also issues a session) can therefore involve two separate commit boundaries — not one shared transaction across both sessions.

## Where to go next

- [Ports and Adapters (Repository Pattern)](ports-and-adapters.md) — the general pattern `Flusher`/`TransactionManager` are one instance of, and every other port/adapter pair in the codebase.
- [Domain Events & the Transactional Outbox](domain-events-outbox.md) — why `stage()` has to run *before* this same commit boundary, not after.
- [Dependency Injection with Dishka](dependency-injection.md) — how the two `AsyncSession`s and their transaction managers get resolved and scoped per request.
