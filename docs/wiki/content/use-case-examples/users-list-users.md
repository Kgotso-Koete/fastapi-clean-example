# Users: List Users

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/list_users.py`](../../../../src/app/inbound/http/users/list_users.py) — HTTP router
    - [`src/app/core/queries/list_users.py`](../../../../src/app/core/queries/list_users.py) — the `ListUsers` query
    - [`src/app/core/queries/ports/user_reader.py`](../../../../src/app/core/queries/ports/user_reader.py) — `UserReader` port, `ListUsersQm`
    - [`src/app/core/queries/models/user.py`](../../../../src/app/core/queries/models/user.py) — `UserQm` query model
    - [`src/app/core/queries/query_support/offset_pagination.py`](../../../../src/app/core/queries/query_support/offset_pagination.py) — `OffsetPaginationParams`
    - [`src/app/core/queries/query_support/sorting.py`](../../../../src/app/core/queries/query_support/sorting.py) — `SortingParams`, `SortingOrder`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`
    - [`src/app/outbound/adapters/sqla_user_reader.py`](../../../../src/app/outbound/adapters/sqla_user_reader.py) — the `UserReader` adapter
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## This is a query, not a command — and that shows up in the code

Every other page in this section (`Create User`, `Activate User`, `Deactivate User`, `Grant Admin`, `Revoke Admin`, `Set User Password`) is a **command**: it changes state, and lives under `src/app/core/commands/`. `ListUsers` is a **query**: it only reads, and lives under a structurally separate `src/app/core/queries/` tree with its own port (`UserReader` instead of `UserTxStorage`), its own supporting types (`query_support/`), and its own return shape (a `TypedDict` query model, `ListUsersQm`, instead of a domain `User` entity — an **Entity**, i.e. a Domain-Driven Design object with identity that persists over time, per [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are)). `ListUsers`'s own docstring:

- Open to admins.
- Retrieves paginated list of existing users with relevant info.

This is the **CQRS** (Command Query Responsibility Segregation) split this codebase draws deliberately — using structurally separate models and code paths for state-changing commands versus read-only queries, rather than one shared model for both, per [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#the-cqrs-split-and-the-auth-ctx-boundary): commands mutate state and dispatch **Domain Events** (things that happened, like `UserRegisteredEvent`; see the same page) through the entity/`UserService`/outbox machinery covered on every other page in this section; queries have none of that — no entity, no event dispatcher, no transaction manager, no flusher. `ListUsers.__init__` takes only two dependencies: `CurrentUserService` (for authorization) and `UserReader` (for reading) — nothing that writes anything.

## Request flow

!!! figure-wide "GET /users/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as list_users router
        participant Qry as ListUsers.execute()
        participant Authz as authorize(CanManageRole)
        participant Reader as UserReader (port)
        participant DB as SqlaUserReader (adapter)

        Client->>Router: GET /users/?limit=&offset=&sorting_field=&sorting_order=
        Router->>Qry: execute(ListUsersRequest)
        Qry->>Qry: current_user = get_current_user()
        Qry->>Authz: CanManageRole(subject=current_user, target_role=USER)
        alt not satisfied
            Authz-->>Client: 403 Forbidden
        else satisfied
            Qry->>Qry: pagination = OffsetPaginationParams(limit, offset)
            alt limit/offset out of range
                Qry-->>Client: 400 Bad Request (PaginationError)
            else valid
                Qry->>Qry: sorting = SortingParams(field, order)
                Qry->>Reader: list_users(pagination, sorting)
                Reader->>DB: SELECT ... ORDER BY ... LIMIT ... OFFSET ...
                DB-->>Reader: rows
                Reader-->>Qry: ListUsersQm {users, total, limit, offset}
                Qry-->>Router: ListUsersQm
                Router-->>Client: 200 OK, ListUsersQm as JSON
            end
        end
    ```

    > Note the single, coarse `CanManageRole(target_role=USER)` check and nothing else — there is no per-target `CanManageSubordinate` check here, unlike every mutating command in this section, because there is no single target user: this endpoint returns a whole page of users at once, so there is no one target to run a per-target check against. "Open to admins" is enforced entirely by that one `CanManageRole` call.

## Pagination and sorting are validated request-shape concerns, handled in `core`

`ListUsersRequestSchema` (the router's Pydantic model) constrains `limit`/`offset` at the HTTP (HyperText Transfer Protocol) layer via `Field(ge=..., le=...)` against `OffsetPaginationParams.MAX_INT32` — but the real validation authority is `OffsetPaginationParams.__post_init__` itself, in `core`, which raises `PaginationError` if `limit` is outside `[MIN_LIMIT, MAX_INT32]` or `offset` is outside `[MIN_OFFSET, MAX_INT32]`. The Pydantic-level constraint is a convenience that lets Swagger UI show sane bounds and reject obviously-bad input before it ever reaches `core` — but `core`'s own dataclass would catch the same violation on its own regardless of what called it, which is the point: the query's actual validity rules live in `core`, not in the HTTP schema.

`sorting_field` is a `UserSortingField` (`StrEnum`: `USERNAME`, `ROLE`, `IS_ACTIVE`, `CREATED_AT`, `UPDATED_AT`) and `sorting_order` a `SortingOrder` (`ASC`/`DESC`), both defined in `core` — FastAPI/Pydantic validate the incoming query string against these enums automatically, rejecting any other value before the query even runs.

!!! figure "OffsetPaginationParams and SortingParams feeding UserReader"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph inputs["Query string params"]
            limit["limit, offset"]
            sortf["sorting_field"]
            sorto["sorting_order"]
        end
        subgraph core_types["core query_support types"]
            pag["OffsetPaginationParams"]
            sort["SortingParams"]
        end
        reader["UserReader.list_users()"]
        result[("ListUsersQm: users, total, limit, offset")]

        limit --> pag
        sortf --> sort
        sorto --> sort
        pag --> reader
        sort --> reader
        reader --> result

        linkStyle default stroke-width:3px,stroke:#333333
        style inputs stroke-width:1px,stroke:#333333
        style core_types stroke-width:1px,stroke:#333333
    ```

    > Raw query-string values become two validated `core` value types before `UserReader` ever sees them — the adapter behind that port never has to re-validate bounds or an unknown sort field itself.

`ListUsersQm` returns not just the page of `UserQm` rows but also `total` (the full, unpaginated row count) and the `limit`/`offset` that were actually applied — everything a client needs to render "showing 21–40 of 137" without a second round-trip.

## Where to go next

- [Users: Create User](users-create-user.md) — the command side of this same resource; contrast the command/query dependency shapes directly.
- [Adding a New Use Case (Command)](adding-a-use-case.md) — the command-side template; this page is the one query-side counterexample worth reading alongside it.
- [Users: Grant Admin](users-grant-admin.md) — see the resulting role/`is_active` changes this query surfaces.
