# Characterisation Tests

!!! sourcefiles "Relevant Source Files/Folders"
    - [`tests/base/characterisation/main/test_openapi_snapshots.py`](../../../../tests/base/characterisation/main/test_openapi_snapshots.py) and [`openapi_snapshots/`](../../../../tests/base/characterisation/main/openapi_snapshots/cookie_app.json) (`cookie_app.json`, `public_api_app.json`) — both OpenAPI documents, as committed JSON
    - [`tests/base/characterisation/main/test_container_bindings.py`](../../../../tests/base/characterisation/main/test_container_bindings.py) — what every binding in the four DI containers resolves to
    - [`tests/base/characterisation/main/cli/test_cli_commands.py`](../../../../tests/base/characterisation/main/cli/test_cli_commands.py) — the CLI's commands and options
    - [`tests/base/characterisation/outbound/persistence_sqla/mappings/test_mapped_tables.py`](../../../../tests/base/characterisation/outbound/persistence_sqla/mappings/test_mapped_tables.py) — the mapped tables and their classes

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What they are

Tests that pin what the app does **today**, written before [plan 16](../../../../docs/plans/16-modular-monolith.md) moved anything (its Step 0), so every move could prove nothing changed. Unlike [TDD](tdd.md) tests, which start RED, they pass on their first run: they record behaviour, they don't drive it.

!!! figure "What a restructuring step must not change"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        step["a restructuring step<br/>(moves, renames, rewiring)"]

        subgraph pinned["pinned by tests/base/characterisation/"]
            openapi["both OpenAPI documents<br/>= committed JSON"]
            containers["4 DI containers:<br/>each binding's class, absent bindings,<br/>each event's handlers"]
            tables["6 mapped tables<br/>and their classes"]
            cli["the CLI's commands<br/>and options"]
        end

        check["make check"]

        step --> pinned
        pinned --> check

        linkStyle default stroke-width:3px,stroke:#333333
        style pinned stroke-width:1px,stroke:#333333
    ```

    > Every box is compared with what it was before the step. Any difference fails `make check`, even when no behaviour test notices.

## Why each one matters

- **OpenAPI documents** — both apps' documents (`/openapi.json` and `/public/openapi.json`), as served, equal committed JSON, key order included: the order is what Swagger shows.
- **Container bindings** — dishka lets a later provider replace an earlier binding of the same type without any error, so a provider registered twice or in another order would change behaviour silently. The test also pins what a container must *not* bind, such as organization writes on the public API.
- **Mapped tables** — every entrypoint and Alembic's `env.py` call `map_tables()`; a table missing from it would make `make migration` generate a `DROP TABLE`.
- **CLI commands** — the commands and options are what people and scripts (cron jobs, seeding) type.

## Where they run

`tests/base/characterisation/` is in the light tier, so `make check` runs it every time (see [Running Tests](running-tests.md)). None of it needs a database. The mapped-tables test maps the tables in a separate Python process, because mapping can't be undone inside one and would change the conditions of every unit test after it.

## When one fails

First decide which kind of failure it is:

- **A regression** — the step changed something it shouldn't have. Fix the code; the test stays as it is.
- **An intended change** — a new route, binding or table, as adding a module brings (see [Units: base, Modules and shared](../architecture/units.md)). Update the pinned value in its own reviewed step. For the bindings, tables and CLI commands, edit the expected value in the test. The OpenAPI snapshots are rewritten by [`test_openapi_snapshots.py`](../../../../tests/base/characterisation/main/test_openapi_snapshots.py) itself, run from the repository root, and then you review the diff of `openapi_snapshots/`:

```shell
uv run python -m tests.base.characterisation.main.test_openapi_snapshots
```

## Where to go next

- [Running Tests](running-tests.md) — the light tier these tests run in.
- [TDD (Red-Green-Refactor)](tdd.md) — the tests that drive new behaviour, as opposed to these, which pin existing behaviour.
- [Units: base, Modules and shared](../architecture/units.md) — the restructuring these tests were written for.
