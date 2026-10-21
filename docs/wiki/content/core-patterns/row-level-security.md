# Row-Level Security (RLS)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`docs/plans/14-row-level-security.md`](../../../../docs/plans/14-row-level-security.md) — the plan: design, decisions, TDD steps
    - [`src/app/outbound/persistence_sqla/row_level_security.py`](../../../../src/app/outbound/persistence_sqla/row_level_security.py) — **the security model** (`TABLE_RULES`: every table's class, grants and policies) and the generator that turns it into migrations
    - [`src/app/outbound/persistence_sqla/alembic/env.py`](../../../../src/app/outbound/persistence_sqla/alembic/env.py) — hooks the generator into `make migration`
    - [`scripts/postgres/initdb/10-create-runtime-role.sh`](../../../../scripts/postgres/initdb/10-create-runtime-role.sh) — creates the database roles on a fresh volume
    - [`src/app/main/config/settings.py`](../../../../src/app/main/config/settings.py) — `PostgresRuntimeRoleSettings` (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`)
    - [`tests/integration/with_infra/row_level_security/`](../../../../tests/integration/with_infra/row_level_security/) — the runtime role, the catalog guard and the isolation matrix

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

!!! warning "Work in progress: the database is protected, the app isn't yet"
    Built: **Steps 1–2 of 15** (roles, security model, generator, catalog guard); **Step 3 under way** (policies). Parts marked *planned* aren't built yet.

    The web app still connects as `postgres`, a superuser that skips every policy, until Step 7. So today RLS protects the database against the runtime login only, not the running app.

## Why

!!! figure "One forgotten filter, with and without RLS"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "useMaxWidth": false}}}%%
    flowchart LR
        bug["New code forgets<br/>WHERE organization_id = ..."]
        bug --> today["Without RLS<br/>every organization's rows<br/>(a data leak)"]
        bug --> rls["With RLS<br/>only the bound organization's rows,<br/>or none at all"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

## Docker vs Postgres

Docker runs the boxes. Postgres stores the data and decides who may see it.

!!! figure "Who does what"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph docker["Docker: starts containers, passes settings"]
            app["app container<br/>web + public API"]
            worker["worker container<br/>Celery"]
            initdb["scripts/postgres/initdb/<br/>(mounted read-only)"]
            subgraph dbpg["db_pg container"]
                subgraph pg["Postgres: data, roles, permissions"]
                    roles["Roles<br/>postgres · app_runtime · app_user"]
                    tables["Tables + grants + RLS policies"]
                end
            end
        end
        initdb -.->|"runs once, on a fresh volume"| roles
        app -->|"migrations at start: as postgres"| tables
        app -->|"requests: as app_user (planned, Step 7)"| tables
        worker -->|"as postgres"| tables

        linkStyle default stroke-width:3px,stroke:#333333
    ```

!!! figure "Start-up order"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}}}%%
    sequenceDiagram
        participant D as Docker
        participant P as Postgres
        participant M as Migrations (as postgres)
        participant A as Web app
        D->>P: start with an empty data folder
        P->>P: init script creates app_runtime + app_user
        D->>M: start app container, run alembic upgrade head
        M->>P: create tables (owner: postgres)
        M->>P: GRANT rights to app_runtime + ENABLE RLS
        M->>P: CREATE POLICY ... TO app_runtime (Step 3, under way)
        D->>A: start the web app
        A->>P: every request runs as app_user (planned, Step 7)
    ```

## Roles

!!! figure "Logins, groups and memberships"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 30, "padding": 10, "useMaxWidth": false}}}%%
    flowchart TB
        postgres["postgres<br/>superuser · owns every table<br/>ignores all RLS"]
        subgraph customer["Customer side (built, Step 1)"]
            app_user["app_user<br/>LOGIN"] -->|"INHERIT TRUE · SET FALSE<br/>uses the grants, can't become it"| app_runtime["app_runtime<br/>group · NOLOGIN<br/>receives every grant + policy"]
        end
        subgraph staff["Staff side (planned, Steps 10-14)"]
            staff_login["staff login<br/>LOGIN · NOINHERIT"] -->|"INHERIT FALSE · SET TRUE<br/>must SET LOCAL ROLE first"| op_read["app_operator_read<br/>reads every organization"]
            staff_login -->|"INHERIT FALSE · SET TRUE"| op_write["app_operator_write<br/>+ updates named columns only"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
    ```

| Role | Logs in | RLS applies | Used by |
|---|---|---|---|
| `postgres` | yes | no (superuser) | migrations, worker, CLI, seed script |
| `app_user` | yes | yes, through `app_runtime` | web app and public API (planned, Step 7) |
| `app_runtime` | no | yes | nobody directly: it holds the grants |
| staff login | yes | yes, after `SET LOCAL ROLE` | staff routes (planned) |
| `app_operator_read` / `_write` | no | yes | staff transactions (planned) |

## Two locks on every query

!!! figure "GRANT decides what, POLICY decides which rows"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 20, "padding": 10, "useMaxWidth": false}}}%%
    flowchart LR
        q["SQL from the app"] --> who{"Who is asking?"}
        who -->|"superuser · BYPASSRLS · table owner"| all["every row<br/>(policies skipped)"]
        who -->|"app_user"| g{"Lock 1: GRANT<br/>this command, on this<br/>table or column?"}
        g -->|"no"| e1["error 42501"]
        g -->|"yes"| p{"Lock 2: POLICY<br/>which rows?"}
        p -->|"SELECT / UPDATE / DELETE:<br/>row fails USING"| hide["silently skipped<br/>(0 rows, no error)"]
        p -->|"INSERT / UPDATE:<br/>new row fails WITH CHECK"| e2["error 42501"]
        p -->|"allowed"| ok["rows returned / written"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

"No error" never proves a write worked: a blocked UPDATE or DELETE just matches 0 rows. The tests prove writes with `RETURNING`.

## Changing the rules

1. Edit `TABLE_RULES` in `row_level_security.py`. A new table must be added there, or the catalog guard fails.
2. Run `make migration`. The generator compares the model with the live database and writes the SQL plus its exact reverse.
3. Never hand-write a grant or policy into a migration. Never edit a committed policy; add a new one (`..._v2`).

## What's in place

| Table | RLS | Policies (all `TO app_runtime`) |
|---|---|---|
| `organization_memberships` | on | `SELECT`, `INSERT`, `UPDATE`, `DELETE`: only rows of the bound organization |
| `organizations` | on | none yet, so `app_user` sees nothing (default deny) |
| `users`, `auth_sessions`, `api_keys` | off | n/a: protected by the app's own checks |
| `event_outbox` | off | n/a: `app_user` may only `INSERT` |

`FORCE ROW LEVEL SECURITY` is **off on purpose**: on managed Postgres the owner isn't a superuser, so `FORCE` would make the owner behave differently than in dev and test.

**Proven by tests** (as the real runtime login, plain SQL with no `WHERE organization_id`): only the bound organization's rows are visible; nothing bound means nothing visible, on fresh and reused connections; a garbage context errors; writes inside the bound organization work. **Not yet proven:** cross-organization writes are refused.

## One request (planned, Steps 5-7)

!!! figure "The organization is bound for one transaction only"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}}}%%
    sequenceDiagram
        participant R as Request
        participant U as Use case
        participant P as Postgres (as app_user)
        R->>U: list members of organization X
        U->>P: is the caller an accepted member of X?
        P-->>U: yes
        U->>P: set_config('app.current_organization_id', X, true)
        Note over P: true = this transaction only
        U->>P: SELECT ... FROM organization_memberships
        Note over P: policy adds organization_id = X
        P-->>U: only X's rows
        U->>P: COMMIT
        Note over P: setting is now '' → NULLIF → NULL<br/>next request on this connection sees no rows
    ```

## Staff access (planned, Steps 10-14)

!!! figure "Staff pick a role per transaction"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}}}%%
    sequenceDiagram
        participant S as Staff use case
        participant P as Postgres (as staff login)
        S->>P: staff grant checked (read or write)
        S->>P: SET LOCAL ROLE app_operator_read
        S->>P: SELECT ... any organization, any filter
        P-->>S: rows from every organization
        Note over S,P: writes use app_operator_write:<br/>only granted columns, plus an audit row<br/>in the same transaction
    ```
