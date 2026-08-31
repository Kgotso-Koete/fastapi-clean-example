# Database (Postgres)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/outbound/persistence_sqla/registry.py`](../../../../src/app/outbound/persistence_sqla/registry.py) — the shared `MetaData`/`registry` every table maps into, plus the naming convention for constraints
    - [`src/app/outbound/persistence_sqla/mappings/`](../../../../src/app/outbound/persistence_sqla/mappings/) — imperative table definitions and `map_*_table()` functions (`user.py`, `auth_session.py`, `outbox_message.py`, `all.py`)
    - [`src/app/outbound/persistence_sqla/constraint_names.py`](../../../../src/app/outbound/persistence_sqla/constraint_names.py) — named unique-constraint constants used to translate raw `IntegrityError`s into domain-meaningful exceptions
    - [`src/app/outbound/persistence_sqla/alembic/`](../../../../src/app/outbound/persistence_sqla/alembic/) — `env.py`, `script.py.mako`, and every migration under `versions/`
    - [`alembic.ini`](../../../../alembic.ini) — Alembic's own config, pointed at the `alembic/` folder above
    - [`src/app/main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py) — `PersistenceSqlaProvider`, the DI (Dependency Injection) wiring that turns `PostgresSettings`/`SqlaSettings` into a live `AsyncEngine`/`AsyncSession`
    - [`docker-compose.yml`](../../../../docker-compose.yml) — the `db_pg` service
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — the `start`/`pytest` cases, both of which run `alembic upgrade head` before anything else
    - [`env.example`](../../../../env.example) — every `POSTGRES_*` variable, documented inline
    - [`Makefile`](../../../../Makefile) — the `migration` target

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What runs where

Postgres is the one piece of infrastructure this app cannot start without — see the Overview's [container topology](../../index.md#what-actually-runs): `app --> db_pg` is the one `depends_on` edge that's never optional, regardless of `CELERY_ENABLED` or `ENVIRONMENT`. `db_pg` runs `postgres:18-alpine`, exposes `127.0.0.1:${POSTGRES_PORT:-5432}:5432`, and gates every other service that touches it (`app`, `worker`, `adminer`) behind a `pg_isready` healthcheck.

!!! figure "App process to Postgres: the connection path"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph appscope["Scope.APP -- built once per process"]
            engine["AsyncEngine\n(create_async_engine)"]
            sessionfactory["async_sessionmaker"]
        end

        subgraph reqscope["Scope.REQUEST -- built once per HTTP request"]
            primary["primary AsyncSession\n(core commands/queries)"]
            authsession["auth AsyncSession\n(auth_ctx: sessions, login)"]
        end

        engine --> sessionfactory
        sessionfactory --> primary
        sessionfactory --> authsession
        primary --> db_pg[("db_pg\npostgres:18-alpine")]
        authsession --> db_pg

        linkStyle default stroke-width:3px,stroke:#333333
        style appscope stroke-width:1px,stroke:#333333
        style reqscope stroke-width:1px,stroke:#333333
    ```

    > `PersistenceSqlaProvider` (in [`main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py)) builds exactly one `AsyncEngine` and one `async_sessionmaker` for the whole process lifetime (`Scope.APP`), using `PostgresSettings.dsn` (`postgresql+psycopg://...`) and `SqlaSettings` (`ECHO`, `ECHO_POOL`, `POOL_SIZE=15`, `MAX_OVERFLOW=0`, plus `connect_args={"connect_timeout": 5}` and `pool_pre_ping=True` so a stale connection is detected and replaced rather than handed to a request). Every incoming HTTP (Hypertext Transfer Protocol) request then gets **two independent `AsyncSession`s** from that one session factory — one for the core account/user context, one for the separate `auth_ctx` package (sessions, login) — each opened and closed within that request's own `Scope.REQUEST` container. Both ultimately talk to the same `db_pg` container; the split is a Clean Architecture/bounded-context boundary (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what Clean Architecture means here, and [Outbound Layer (Infrastructure Adapters)](../architecture/outbound-layer.md) for what a bounded context is), not a physical database split.

## Imperative mapping, not the Declarative API (Application Programming Interface)

Domain entities (`User`, `AuthSession`, the outbox's `OutboxMessage` — an **entity** is a Domain-Driven Design building block for something with identity that persists over time; see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)) are plain Python classes defined in `app.core`/`app.outbound.auth_ctx` — they know nothing about SQLAlchemy. Each table under [`mappings/`](../../../../src/app/outbound/persistence_sqla/mappings/) instead declares a plain `sqlalchemy.Table` against the shared `mapper_registry.metadata` (from [`registry.py`](../../../../src/app/outbound/persistence_sqla/registry.py)), then calls `mapper_registry.map_imperatively(EntityClass, table, properties={...})` to imperatively bind ORM (Object-Relational Mapping) attributes onto that already-existing class. [`mappings/all.py`](../../../../src/app/outbound/persistence_sqla/mappings/all.py)'s `map_tables()` is the single entry point that runs every `map_*_table()` function once (guarded by `if mapper_registry.mappers: return`), and it's called from two places that otherwise share nothing else: [`app.main.run`](../../../../src/app/main/run.py)'s lifespan for the web process, and Alembic's own [`env.py`](../../../../src/app/outbound/persistence_sqla/alembic/env.py) for migrations — a mapped class like `OutboxMessage` can't be queried or autogenerated against until this has run.

`registry.py`'s `MetaData` also carries a shared naming convention (`ix_%(column_0_label)s`, `uq_%(table_name)s_%(column_0_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, ...), so every constraint Alembic autogenerates gets a deterministic, greppable name instead of a driver-assigned one — [`constraint_names.py`](../../../../src/app/outbound/persistence_sqla/constraint_names.py)'s `UQ_USERS_USERNAME`/`UQ_USERS_EMAIL`/`UQ_USERS_PHONE_NUMBER` constants exist precisely so outbound adapters can pattern-match a raised `IntegrityError`'s constraint name back to a specific, human-meaningful conflict (e.g. "username already taken" vs "phone number already taken") instead of guessing from a raw driver error string.

Three tables exist today: `users` (with a composite `Username`/`Email`/`PhoneNumber`/`UtcDatetime` value-object (a Domain-Driven Design building block for something defined purely by its value, not identity; see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)) mapping via SQLAlchemy's `composite()`), `auth_sessions` (`ON DELETE CASCADE` to `users.id`), and `event_outbox` (the transactional outbox — see [Core Patterns → Domain Events & Outbox](../core-patterns/domain-events-outbox.md) and [Background Jobs](background-jobs.md) for what writes to and drains it).

## Migrations: writing one, and applying them

!!! figure "Writing a migration vs. applying migrations at startup"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph author["Authoring a migration (make migration msg=...)"]
            infra["INFRA_INIT_SERVICES\n(db_pg) started"] --> autogen["alembic revision\n--autogenerate"]
            autogen --> maptables1["map_tables() registers\nevery mapping first"]
            maptables1 --> diff["diffed against\nmapper_registry.metadata"]
            diff --> versionfile["new file in\nalembic/versions/"]
            versionfile --> stairway["stairway test replays\nevery migration up+down"]
        end

        subgraph apply["Applying at container startup"]
            entrypoint["docker-entrypoint.sh\n'start' / 'pytest' case"] --> upgrade["alembic upgrade head"]
            upgrade --> uvicorn["exec uvicorn\napp.main.run:make_app"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style author stroke-width:1px,stroke:#333333
        style apply stroke-width:1px,stroke:#333333
    ```

    > The two flows above never touch the same running process. `make migration msg=<description>` (the `Makefile` target) starts just enough infrastructure (`db_pg`) to run `alembic revision --autogenerate`, which loads every mapping via `map_tables()` and diffs the resulting `mapper_registry.metadata` against the live schema to generate a new file in `alembic/versions/` — always reviewed and adjusted by hand afterward, never trusted blindly (Alembic's own autogenerate is a starting point, not a guarantee). [`env.py`](../../../../src/app/outbound/persistence_sqla/alembic/env.py) itself loads `PostgresSettings` via `load_postgres_settings()` and sets `sqlalchemy.url` from `settings.dsn` — the one place in this codebase explicitly allowed to import `app.main.config.settings` from outside `main` (see [Architecture → Layer Dependencies](../architecture/layer-dependencies.md) for why that's a deliberate, narrow exception).
    >
    > Separately, every time the `app` or `worker` container actually starts (`docker-entrypoint.sh`'s `start` and `pytest` cases), `alembic upgrade head` runs first, unconditionally, before `uvicorn`/`pytest` ever gets control — so a fresh `db_pg` volume is never left on an old schema. Four migrations exist today, in order: `users`, `auth_sessions`, `add_email_and_phone_number_to_users`, and `add_event_outbox_table` (the last one is what backs the [transactional outbox](background-jobs.md)).

## `env.example`'s `POSTGRES_*` variables

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_DB` | `clean-example` | required (`?POSTGRES_DB is required` in `docker-compose.yml` — the container refuses to start without it) |
| `POSTGRES_HOST` | `db_pg` | the one setting whose correct value depends on *where* `app` itself runs — `make upd` needs the Docker-internal service name (`db_pg`); `make upd-local` rewrites this to `127.0.0.1` since the app then runs on your host. **Do not** also set `POSTGRES_HOST` in `.secrets` — it's appended last (last-value-wins) and silently breaks the local path |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_USER` | `postgres` | required |
| `POSTGRES_PASSWORD` | `password` | required |

> All five map straight onto `PostgresSettings` in [`main/config/settings.py`](../../../../src/app/main/config/settings.py), which builds the actual DSN (Data Source Name) (`postgresql+psycopg://...`) via `PostgresDsn.build(...)`.

## Browsing the database

Adminer (dev-only, gated behind `ENVIRONMENT=development` like the rest of the dev tooling — see [Configuration → Deployment Environments](../configuration/deployment-environments.md)) is the fastest way to look inside `db_pg` directly: `http://localhost:8080`, System `PostgreSQL`, Server `db_pg`, User/Password from `env.example`'s defaults, Database `clean-example`.

## Where to go next

- [Background Jobs (Celery / Redis)](background-jobs.md) — the `event_outbox` table's other half: how a worker process drains it.
- [Core Patterns → Domain Events & Outbox](../core-patterns/domain-events-outbox.md) — why the outbox table exists at all (the "dual write" problem).
- [Development Guide → Database Migrations](../development-guide/database-migrations.md) — a closer walkthrough of the `make migration` workflow itself.
