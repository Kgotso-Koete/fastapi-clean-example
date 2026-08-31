# Database Migrations (Alembic)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/outbound/persistence_sqla/alembic/env.py`](../../../../src/app/outbound/persistence_sqla/alembic/env.py) — wires Alembic to this project's real settings and SQLAlchemy mappings
    - [`src/app/outbound/persistence_sqla/alembic/versions/`](../../../../src/app/outbound/persistence_sqla/alembic/versions/) — every real migration file, in date order
    - [`src/app/outbound/persistence_sqla/alembic/script.py.mako`](../../../../src/app/outbound/persistence_sqla/alembic/script.py.mako) — the template every new migration file is generated from
    - [`alembic.ini`](../../../../alembic.ini) — `file_template`, controlling the `YYYY-MM-DD_HHMMSS_<slug>.py` filenames
    - [`scripts/makefile/migration.sh`](../../../../scripts/makefile/migration.sh) — what `make migration` actually runs
    - [`tests/integration/migrations/test_stairway.py`](../../../../tests/integration/migrations/test_stairway.py) — the "stairway" test that walks every migration up and down
    - [`tests/integration/conftest.py`](../../../../tests/integration/conftest.py) — the `allow_destructive` safety-guard fixture the stairway test requires

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

This project uses [Alembic](https://alembic.sqlalchemy.org/) to version-control the Postgres schema, driven from the same SQLAlchemy table mappings the app itself uses at runtime (see [Data Models → Database Models](../data-models/database-models.md)) — there's exactly one source of truth for what the schema looks like, not a separately hand-maintained set of `CREATE TABLE` scripts.

## Generating a new migration

`make migration msg="<short description>"` is the only supported way to create one. It doesn't just call `alembic revision --autogenerate` directly — it wraps that in a disposable, isolated database and a correctness check:

!!! figure "make migration msg=&quot;...&quot; — the full generation flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart TB
        start["make migration msg=&quot;add widgets&quot;"] --> localenv["local-env: regenerate .env<br/>(scripts/makefile/local_env.sh)"]
        localenv --> spinup["docker compose -p &lt;dir&gt;-migration up -d --build --wait<br/>starts MIGRATION_DB_SERVICE (db_pg) only"]
        spinup --> upgrade["uv run alembic upgrade head<br/>bring the throwaway db to the current schema"]
        upgrade --> autogen["uv run alembic revision --autogenerate -m msg<br/>diff SQLAlchemy mappings vs. the db, write versions/*.py"]
        autogen --> stairway["pytest test_stairway.py<br/>(if STAIRWAY_TEST is set)"]
        stairway --> teardown["docker compose down -v --remove-orphans<br/>(trap on EXIT — runs even if a step above failed)"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

Every step above is a real line in [`scripts/makefile/migration.sh`](../../../../scripts/makefile/migration.sh). Two details worth calling out:

- The database this runs against is **not** your regular dev stack's `db_pg` — `migration.sh` starts its own, in a separately-named Compose project (`<dir>-migration`), so generating a migration never touches whatever data you already have sitting in your normal `make upd`/`make upd-local` database. The `trap ... EXIT` line tears it down unconditionally, success or failure.
- `alembic upgrade head` runs *before* `revision --autogenerate` for a reason: autogenerate works by diffing the *current* database schema against `target_metadata` (the SQLAlchemy mappings) — if the throwaway database weren't already at `head`, the diff would include every migration since the database's actual state, not just what's new since the last migration.

## How Alembic knows what "the current models" look like

[`env.py`](../../../../src/app/outbound/persistence_sqla/alembic/env.py) is what connects Alembic's generic machinery to this specific codebase:

```python
map_tables()
target_metadata = mapper_registry.metadata
...
settings: PostgresSettings = load_postgres_settings()
config.set_main_option("sqlalchemy.url", settings.dsn)
```

`map_tables()` runs the same SQLAlchemy imperative mappings the app uses at runtime (see [Data Models → Database Models](../data-models/database-models.md)) — so `target_metadata` autogenerate diffs against is always the real, current set of mapped tables, never a separately-maintained copy. The connection URL (Uniform Resource Locator) comes from `load_postgres_settings()` — the same [Settings System](../configuration/settings-system.md) the app itself uses, read from whatever `.env` is active — not a hardcoded connection string. `env.py` runs migrations through an async engine (`async_engine_from_config` + `asyncio.run(run_async_migrations())`), matching the fact that the rest of this codebase's persistence layer is async throughout.

## Migration file anatomy

Every file under [`alembic/versions/`](../../../../src/app/outbound/persistence_sqla/alembic/versions/) follows the same shape, generated from [`script.py.mako`](../../../../src/app/outbound/persistence_sqla/alembic/script.py.mako). Take [`2026-08-21_151755_add_event_outbox_table.py`](../../../../src/app/outbound/persistence_sqla/alembic/versions/2026-08-21_151755_add_event_outbox_table.py) (the migration that added the transactional outbox's table — see [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md)):

```python
revision: str = "6376b41ed669"
down_revision: Union[str, Sequence[str], None] = "16620e21528f"

def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        ...
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_outbox")),
    )

def downgrade() -> None:
    op.drop_table("event_outbox")
```

- **Filename**: `alembic.ini`'s `file_template = %%(year)d-%%(month).2d-%%(day).2d_%%(hour).2d%%(minute).2d%%(second).2d_%%(slug)s` — a sortable timestamp prefix plus the `msg` you passed to `make migration`, so `ls` on the `versions/` folder already shows them in chronological order without needing to open each file.
- **`revision`/`down_revision`**: a random hex id for this migration, and the hex id of the migration it chains onto — this linked list, not the filename, is what Alembic actually walks; `down_revision = None` marks the very first migration ([`2026-04-01_222815_users.py`](../../../../src/app/outbound/persistence_sqla/alembic/versions/2026-04-01_222815_users.py)).
- **`upgrade()`/`downgrade()`**: autogenerated from the schema diff, but the `# please adjust!` comment autogenerate leaves in every new file is a real warning, not boilerplate — autogenerate reliably catches structural changes (new tables/columns/constraints) but won't write data migrations (backfilling a new non-nullable column, for instance) for you; that part is always manual.

## Applying migrations: where `alembic upgrade head` actually runs

There's no single "the app runs migrations" step — it happens at a few different points depending on which path you're running, and it's always paired with whatever process is about to use that database:

!!! figure "Every place `alembic upgrade head` runs, and what follows it"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph dockerstart["docker-entrypoint.sh: start"]
            s1["alembic upgrade head"] --> s2["exec uvicorn --reload"]
        end

        subgraph dockertest["docker-entrypoint.sh: pytest"]
            t1["alembic upgrade head"] --> t2["exec pytest ..."]
        end

        subgraph localdev["Quick Start Locally"]
            l1["alembic upgrade head (you run this)"] --> l2["uvicorn --reload (host process)"]
        end

        subgraph gen["make migration"]
            g1["alembic upgrade head"] --> g2["alembic revision --autogenerate"] --> g3["stairway test"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style dockerstart stroke-width:1px,stroke:#333333
        style dockertest stroke-width:1px,stroke:#333333
        style localdev stroke-width:1px,stroke:#333333
        style gen stroke-width:1px,stroke:#333333
    ```

    > `docker-entrypoint.sh`'s `start` case (used by the `app`/`worker`/`wiki` Compose services) and its `pytest` case (used by `make test-docker-app`/`make test-docker-migrations`, which run `docker compose run app pytest ...`) both call `alembic upgrade head` before doing anything else — the container never serves traffic or runs a test suite against a database that isn't already at the latest schema. On [Quick Start Locally](../getting-started/quick-start-local.md), there's no entrypoint script involved at all — you run `alembic upgrade head` yourself, once, before starting `uvicorn` directly.

## The stairway test

[`tests/integration/migrations/test_stairway.py`](../../../../tests/integration/migrations/test_stairway.py) is a correctness check on the migrations themselves, not on application behavior — for every revision from the very first migration up to `head`, in order, it does:

```python
upgrade(alembic_config, revision.revision)
downgrade(alembic_config, str(revision.down_revision or "-1"))
upgrade(alembic_config, revision.revision)
```

i.e. upgrade to that revision, downgrade back one step, then upgrade forward again — parametrized so every single migration in the chain gets this treatment, not just the newest one. This catches a specific, easy-to-miss class of bug: a `downgrade()` that was never actually tested (because in normal use nobody downgrades), left broken, incomplete, or referencing a column/type that a *later* migration already renamed or dropped. `make migration` runs this test automatically against every new migration (via `STAIRWAY_TEST` in the Makefile) before the throwaway database is torn down, and [`make test-docker-migrations`](makefile-commands.md#testing) runs it independently against the full existing chain.

The test requires the session-scoped `allow_destructive` fixture from [`tests/integration/conftest.py`](../../../../tests/integration/conftest.py), which raises `pytest.UsageError` unless `ALLOW_DESTRUCTIVE_TEST_CLEANUP=1` is set in the environment — a deliberate guard, since repeatedly upgrading/downgrading is exactly the kind of destructive operation you don't want silently possible against whatever database happens to be configured. Both `migration.sh` and the Docker test Compose override (`docker-compose.test.yml`) set this explicitly rather than leaving it to chance.

## Applying an existing migration yourself

Outside of the automated paths above, the plain Alembic CLI (Command-Line Interface) works as normal once your environment's `DATABASE_URL`/`POSTGRES_*` settings point at a real Postgres:

```shell
alembic upgrade head       # apply every migration not yet applied
alembic downgrade -1       # roll back exactly one migration
alembic current            # show which revision the database is actually at
alembic history            # list every revision in order
```

Inside a running Docker container, prefix these with `docker compose exec app` (see [Docker Development Environment → Attaching a shell](docker-development.md#attaching-a-shell-to-a-running-container)) or run them directly if you've shelled in already.

## Where to go next

- **Want the full Makefile command reference, not just `make migration`?** [Makefile Commands Reference](makefile-commands.md).
- **Curious what the mapped tables actually look like?** [Data Models → Database Models](../data-models/database-models.md).
- **Wondering why `event_outbox` exists at all?** [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md).
