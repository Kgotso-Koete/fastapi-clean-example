# Outbound Layer (Infrastructure Adapters)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/outbound/adapters/`](../../../../src/app/outbound/adapters/) — concrete implementations of `core`'s ports
    - [`src/app/outbound/auth_ctx/`](../../../../src/app/outbound/auth_ctx/) — a second, independent adapter tree for session/JWT auth
    - [`src/app/outbound/persistence_sqla/`](../../../../src/app/outbound/persistence_sqla/) — SQLAlchemy table definitions and imperative mappings
    - [`src/app/outbound/adapters/sqla_transaction_manager.py`](../../../../src/app/outbound/adapters/sqla_transaction_manager.py) and [`src/app/outbound/auth_ctx/sqla_transaction_manager.py`](../../../../src/app/outbound/auth_ctx/sqla_transaction_manager.py) — the same idea, implemented twice, deliberately

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What lives here

`outbound` is the layer that talks to the outside world on `core`'s behalf: Postgres via SQLAlchemy, bcrypt, SMTP, Celery's outbox relay, JWT encoding. Per [Layer Dependencies & Import Rules](layer-dependencies.md), it may import `core` freely but never `inbound` or `main`. Every class here implements a port `core` declared, but `outbound` itself never decides *which* implementation gets used — that's [`main`](main-composition-root.md)'s job.

!!! figure "Adapter to port pairing"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph core_ports["core ports"]
            p_tx["TransactionManager"]
            p_utc["UtcTimer"]
            p_flush["Flusher"]
            p_pwd["PasswordHasher"]
            p_reader["UserReader"]
            p_dispatch["EventDispatcher"]
            p_id["IdentityProvider"]
            p_revoke["AccessRevoker"]
        end
        subgraph outbound_adapters["outbound.adapters"]
            a_tx["SqlaTransactionManager"]
            a_utc["SystemUtcTimer"]
            a_flush["SqlaFlusher"]
            a_pwd["BcryptPasswordHasher"]
            a_reader["SqlaUserReader"]
            a_dispatch["HybridEventDispatcher"]
            a_id["AuthSessionIdentityProvider"]
            a_revoke["AuthSessionAccessRevoker"]
        end

        a_tx -->|implements| p_tx
        a_utc -->|implements| p_utc
        a_flush -->|implements| p_flush
        a_pwd -->|implements| p_pwd
        a_reader -->|implements| p_reader
        a_dispatch -->|implements| p_dispatch
        a_id -->|implements| p_id
        a_revoke -->|implements| p_revoke

        linkStyle default stroke-width:3px,stroke:#333333
        style core_ports stroke-width:1px,stroke:#333333
        style outbound_adapters fill:#b3b3b3,stroke-width:1px,stroke:#333333
    ```

    > Every adapter in [`src/app/outbound/adapters/`](../../../../src/app/outbound/adapters/) fulfills exactly one port `core` declared, and is named after what it does, not what it implements — e.g. `SqlaUserReader` implements `UserReader`, `BcryptPasswordHasher` implements `PasswordHasher`. `AuthSessionIdentityProvider` and `AuthSessionAccessRevoker` are thin wrappers around `AuthService` (from the second adapter tree below), letting `core`'s `IdentityProvider`/`AccessRevoker` ports be satisfied by session-based auth without `core` ever knowing sessions exist.

## Why two parallel adapter trees

[`adapters/`](../../../../src/app/outbound/adapters/) implements `core`'s ports directly — every class there is reachable by tracing "what implements this `Protocol` from `core.commands.ports` or `core.common.ports`." [`auth_ctx/`](../../../../src/app/outbound/auth_ctx/) is a second, self-contained tree that isn't `core`-facing at all: it's the concrete machinery behind login/logout/signup/change-password — `AuthService`, `CookieManager`, `JwtProcessor`, `AuthSession` — none of which fulfill a `core` port directly.

!!! figure "The two trees, and the one allowed bridge between them"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 30, "rankSpacing": 90, "padding": 20, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph adapters_tree["outbound.adapters — core-facing"]
            a_other["SqlaTransactionManager, SqlaUserReader,<br/>BcryptPasswordHasher, SystemUtcTimer,<br/>SqlaFlusher, HybridEventDispatcher"]
            a_id["AuthSessionIdentityProvider"]
            a_revoke["AuthSessionAccessRevoker"]
        end

        core_ports(["core ports<br/>(see 'Adapter to port pairing' above)"])

        subgraph auth_ctx_tree["outbound.auth_ctx — self-contained"]
            handlers["LogIn / SignUp / LogOut /<br/>ChangePassword handlers"]
            svc["AuthService"]
            deps["AuthSessionUtcTimer, AuthSessionSqlaTxStorage,<br/>AuthSqlaTransactionManager, JwtProcessor,<br/>CookieManager"]
            session["AuthSession"]
        end

        a_other -->|implements| core_ports
        a_id -->|implements| core_ports
        a_revoke -->|implements| core_ports

        handlers --> svc
        svc --> deps
        svc -->|creates/reads| session

        a_id -.->|allowed: adapters may import auth_ctx| svc
        a_revoke -.->|allowed| svc

        auth_ctx_tree -. forbidden: auth_ctx must not import adapters .-> adapters_tree

        linkStyle default stroke-width:3px,stroke:#333333
        linkStyle 8 stroke:#c0392b,stroke-width:3px
        style adapters_tree fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style auth_ctx_tree stroke-width:1px,stroke:#333333
    ```

    > The arrow direction matters: `adapters/`'s two wrapper classes are allowed to import `auth_ctx.service.AuthService` — [`AuthSessionIdentityProvider`](../../../../src/app/outbound/adapters/auth_session_identity_provider.py) and [`AuthSessionAccessRevoker`](../../../../src/app/outbound/adapters/auth_session_access_revoker.py) both take an `AuthService` in their constructor and delegate straight to it (`get_current_user_id()`, `revoke_all_sessions()`) — but the reverse import, `auth_ctx` reaching into `adapters`, is the one the `forbidden` contract below blocks. This is how `core`'s `IdentityProvider`/`AccessRevoker` ports get satisfied by session-based auth without `core`, or even `auth_ctx` itself, ever depending on the other adapter tree.

[`AuthSession`](../../../../src/app/outbound/auth_ctx/model.py)'s own docstring explains why `auth_ctx` is shaped as its own separate tree in the first place, rather than as `core` ports from the start:

```python
@dataclass(eq=False, kw_only=True)
class AuthSession:
    """
    This class can become a domain entity in a new bounded context, enabling
    a monolithic architecture to become modular, while the other classes working
    with it are likely to become core and outbound layer components.

    For example, `LogIn` can become an interactor.
    """
```

In other words, `auth_ctx` is deliberately kept as its own small **bounded context** — a Domain-Driven Design term (also [Eric Evans'](https://martinfowler.com/bliki/BoundedContext.html)) for an explicit boundary within which one particular domain model and its own vocabulary apply consistently, and outside of which the same word can mean something else. A large system is split into several bounded contexts rather than one shared model for everything, with well-defined seams between them instead of every part reaching into every other part's internals. `auth_ctx` isn't a *full* bounded context today — it's plain infrastructure code sitting inside `outbound`, not a separately deployable module with its own `core`-style ports — but it's already shaped along the seam one would become: the `AuthSession`/`AuthService`/handler split above is precisely the shape a real "auth" bounded context's entity/service/interactor split would take, which is exactly what its docstring means by "can become a domain entity in a new bounded context." Session management isn't (yet) modeled as a `core` use case with its own ports, it's plain infrastructure code that happens to sit in `outbound`. The `LogIn`/`SignUp`/`LogOut`/`ChangePassword` handlers under [`auth_ctx/handlers/`](../../../../src/app/outbound/auth_ctx/handlers/) look and read like `core.commands` use cases (a `*Request` dataclass, an `execute()` method, injected ports) but live here instead, because they orchestrate [`AuthService`](../../../../src/app/outbound/auth_ctx/service.py) directly rather than going through a `core`-declared port.

A dedicated `forbidden` contract in [`pyproject.toml`](../../../../pyproject.toml) keeps the two trees from merging back together:

```toml
[[tool.importlinter.contracts]]
id = "auth-ctx"
name = "auth-ctx must use its own adapters"
source_modules = ["app.outbound.auth_ctx"]
forbidden_modules = ["app.outbound.adapters"]
```

`auth_ctx` may never import `adapters` — so it can't reach for `SqlaTransactionManager`, `SqlaUserReader`, or any other class from the `core`-facing tree, even though both live under `outbound` and both ultimately wrap the same Postgres database.

### A concrete duplication: two transaction managers

[`adapters/sqla_transaction_manager.py`](../../../../src/app/outbound/adapters/sqla_transaction_manager.py) and [`auth_ctx/sqla_transaction_manager.py`](../../../../src/app/outbound/auth_ctx/sqla_transaction_manager.py) do almost identical work — wrap `session.commit()`, catch `SQLAlchemyError`, re-raise as `StorageError` — but are two separate classes.

[`adapters/sqla_transaction_manager.py`](../../../../src/app/outbound/adapters/sqla_transaction_manager.py):

```python
class SqlaTransactionManager(TransactionManager):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except SQLAlchemyError as e:
            raise StorageError(DB_COMMIT_FAILED) from e
```

[`auth_ctx/sqla_transaction_manager.py`](../../../../src/app/outbound/auth_ctx/sqla_transaction_manager.py):

```python
class AuthSqlaTransactionManager:
    def __init__(self, session: AuthAsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except SQLAlchemyError as e:
            raise StorageError(DB_COMMIT_FAILED) from e
```

Two differences matter: `SqlaTransactionManager` explicitly subclasses `core.commands.ports.transaction_manager.TransactionManager` (it fulfills a real `core` port, and is wired into `core.commands.*` use cases via [`main/ioc/core.py`](../../../../src/app/main/ioc/core.py)) and takes a plain `AsyncSession`. `AuthSqlaTransactionManager` subclasses nothing (there's no `core` port for it to fulfill — session management isn't a `core` concern) and takes an `AuthAsyncSession`, a `NewType`-wrapped `AsyncSession` (see [`auth_ctx/types_.py`](../../../../src/app/outbound/auth_ctx/types_.py)) that exists purely so Dishka can inject a *separate* session instance for the auth context, distinct from the primary one `core.commands` use cases share — both sessions point at the same physical database, wired up in [`main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py)'s `provide_primary_async_session`/`provide_auth_async_session`. Same logic, deliberately duplicated rather than shared, so that `auth_ctx` stays fully independent of `core.commands.ports` and the `adapters` tree.

## Persistence: imperative SQLAlchemy mappings

**Declarative vs. imperative, briefly:** the general software-engineering distinction is that *declarative* code states *what* the result should be and lets something else produce it, while *imperative* code states the actual *steps* that produce it. SQLAlchemy's own two mapping styles are exactly that distinction applied to ORM mapping specifically: its more common **declarative** style has a class inherit from a `Base`/`DeclarativeBase`, with columns declared as class attributes right on that class — the mapping and the class definition are one and the same piece of code, stating what the table should look like. Its **imperative** (also called *classical*) style is the reverse: a plain `sqlalchemy.Table` and a plain Python class are defined completely separately, with no inheritance relationship between them, and a separate, explicit step maps one onto the other afterward.

[`persistence_sqla/`](../../../../src/app/outbound/persistence_sqla/) uses the imperative style: it defines plain `sqlalchemy.Table` objects (`users_table`, `auth_sessions_table`, `event_outbox_table`) and maps them onto `core`'s own entity classes (`User`) and `outbound`'s plain data classes (`AuthSession`, `OutboxMessage`) via `mapper_registry.map_imperatively(...)`, rather than using SQLAlchemy's declarative `Base` class. This is precisely what keeps `User` — a `core` entity — free of any SQLAlchemy import: the mapping is registered from the `outbound` side, once, at startup (`map_tables()`, called from both the web process's lifespan and the worker process's `worker_process_init` hook), linking ORM columns to plain Python attributes without the entity itself ever knowing an ORM is involved.

## Where to go next

- [Layer Dependencies & Import Rules](layer-dependencies.md) — the `auth-ctx` contract that keeps these two adapter trees apart, in full.
- [Core Layer (Domain & Business Rules)](core-layer.md) — the ports every class in `adapters/` implements.
- [Main (Composition Root)](main-composition-root.md) — where `SqlaTransactionManager` vs. `AuthSqlaTransactionManager`, and every other adapter, actually gets selected and wired.
