# Query Models (DTOs)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/queries/models/user.py`](../../../../src/app/core/queries/models/user.py) — `UserQm`, the read-side shape of a user
    - [`src/app/core/queries/query_support/offset_pagination.py`](../../../../src/app/core/queries/query_support/offset_pagination.py) — `OffsetPaginationParams`
    - [`src/app/core/queries/query_support/sorting.py`](../../../../src/app/core/queries/query_support/sorting.py) — `SortingParams`, `SortingOrder`
    - [`src/app/core/queries/query_support/exceptions.py`](../../../../src/app/core/queries/query_support/exceptions.py) — `PaginationError`, `SortingError`
    - [`src/app/core/queries/ports/user_reader.py`](../../../../src/app/core/queries/ports/user_reader.py) — the `UserReader` port and `ListUsersQm`, which return/compose `UserQm`
    - [`src/app/core/queries/list_users.py`](../../../../src/app/core/queries/list_users.py) — the use case that consumes these models
    - [`src/app/outbound/adapters/sqla_user_reader.py`](../../../../src/app/outbound/adapters/sqla_user_reader.py) — the adapter that actually builds `UserQm` instances from SQL (Structured Query Language) rows

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Why a separate model for reads

This codebase follows a CQRS-flavored split (CQRS: Command Query Responsibility Segregation — see [Layer Dependencies & Import Rules → The CQRS split and the auth-ctx boundary](../architecture/layer-dependencies.md#the-cqrs-split-and-the-auth-ctx-boundary) for how the boundary is enforced): `src/app/core/commands/` (write-side use cases that load a `User` entity, mutate it, and record domain events) is kept apart from `src/app/core/queries/` (read-side use cases that never touch an entity at all). `UserQm` — "user query model" — is what the query side returns instead of a `User`.

!!! figure "Command side vs. query side: two different shapes for \"a user\""
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph write["Write side (core/commands)"]
            uc["CreateUser.execute()"]
            user["User entity\n(id_, VOs, events)"]
            uc -->|"loads / mutates"| user
        end

        subgraph read["Read side (core/queries)"]
            lu["ListUsers.execute()"]
            qm["UserQm\n(flat DTO, no behavior)"]
            lu -->|"receives"| qm
        end

        reader["SqlaUserReader\n(outbound adapter)"] -->|"SELECT specific columns"| qm

        linkStyle default stroke-width:3px,stroke:#333333
        style write stroke-width:1px,stroke:#333333
        style read stroke-width:1px,stroke:#333333
    ```

    > The write side always goes through the entity, because mutation has to happen somewhere that can enforce invariants and record events. The read side never needs any of that — it just needs to hand data back to a caller — so it uses a model with none of the entity's machinery.

## `UserQm`: what makes it a query model, not an entity

Here is the dataclass itself, verbatim, from [`queries/models/user.py`](../../../../src/app/core/queries/models/user.py) — `id` is a UUID (Universally Unique Identifier), the same identifier type the `User` entity's `id_` uses:

```python
@dataclass(frozen=True, slots=True)
class UserQm:
    id: UUID
    username: str
    email: str
    phone_number: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
```

Three concrete differences from the `User` entity documented in [Domain Entities & Value Objects](domain-entities.md), all visible directly in this dataclass definition:

- **Every field is a plain type**, not a value object. `username` is `str`, not `Username`; `role` is `str`, not `UserRole`; `created_at` is a plain `datetime`, not `UtcDatetime`. There's no validation or normalization here — the data has already been validated once, on the way in through the command side, so re-validating it on the way *out* would be pure overhead with no payoff. A query model's job is to carry already-trustworthy data to a caller, not to guard invariants.
- **No identity semantics, no methods.** `UserQm` doesn't subclass `Entity` and has no `id_`/`record_event`/`collect_events`. It's compared and hashed structurally, like any frozen dataclass — which is fine, because nothing ever needs to ask "is this the same user as some other in-memory reference," only "what were this user's field values at query time."
- **It's a DTO (Data Transfer Object), not a domain concept.** `UserQm` exists purely to move data across a boundary (from the database, out through a use case, out through an HTTP (Hypertext Transfer Protocol) response). It has no behavior at all beyond the constructor `@dataclass` generates. Compare this to `User`, which actively enforces "you cannot change my `id_`" and actively records events when it changes — `UserQm` enforces nothing and records nothing.

This is also why the query side is flatter than the command side: a single `ListUsers` request might return dozens or hundreds of `UserQm` instances built directly from SQL rows (see [`sqla_user_reader.py`](../../../../src/app/outbound/adapters/sqla_user_reader.py)), and building a full `User` entity — with its value-object construction and validation — for each one would be wasted work for a case that's only ever going to serialize the result to JSON (JavaScript Object Notation).

## Pagination and sorting: parameters, not results

`OffsetPaginationParams` and `SortingParams` model the *shape of a query request*, not its result — but they live in the same `query_support/` package because they only make sense for read-side use cases (nothing on the command side asks for "the 3rd page of users to mutate").

!!! figure "Building and validating a list-users request"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        req["ListUsersRequest\n(limit, offset,\nsorting_field, sorting_order)"] --> pp["OffsetPaginationParams(limit, offset)"]
        req --> sp["SortingParams(field, order)"]
        pp -->|"__post_init__ validates"| ppok{"limit/offset\nin range?"}
        ppok -->|"no"| pgerr["raise PaginationError"]
        ppok -->|"yes"| reader["UserReader.list_users(pagination, sorting)"]
        sp --> reader
        reader --> qm["ListUsersQm{ users: list[UserQm], total, limit, offset }"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `OffsetPaginationParams` ([`offset_pagination.py`](../../../../src/app/core/queries/query_support/offset_pagination.py)) is a frozen, keyword-only dataclass holding just `limit` and `offset`, validated in `__post_init__` against `MIN_LIMIT`, `MIN_OFFSET`, and `MAX_INT32` bounds (the `MAX_INT32` cap exists because these values ultimately flow into a Postgres `LIMIT`/`OFFSET` clause, and `int32` is a safe, conservative upper bound for that). An out-of-range value raises `PaginationError`, defined in [`exceptions.py`](../../../../src/app/core/queries/query_support/exceptions.py) alongside its sibling `SortingError` — both subclass the shared `BaseError`, so inbound HTTP code can map them to a 400 the same way it maps `BusinessTypeError` from a bad value object.

`SortingParams` ([`sorting.py`](../../../../src/app/core/queries/query_support/sorting.py)) is even simpler: a `field: str` plus an `order: SortingOrder` (`ASC`/`DESC`, i.e. ascending/descending, `StrEnum`). Notice `field` is a plain `str`, not a `StrEnum` — the *set* of valid sortable fields (`UserSortingField` in [`list_users.py`](../../../../src/app/core/queries/list_users.py)) is defined at the use-case layer, one level up, and `SortingParams` itself stays generic enough to be reused by a future query that sorts something other than users. Validity of the field name against the real table is actually enforced one layer further out still, in [`SqlaUserReader.list_users`](../../../../src/app/outbound/adapters/sqla_user_reader.py) (`users_table.c.get(sorting.field)` returning `None` raises `SortingError`) — a case of the same validation responsibility (`SortingError`) being enforced at the adapter, since only the adapter actually knows which columns exist on the real table.

Both params objects are assembled inside a use case's `execute()` (see `ListUsers.execute` in [`list_users.py`](../../../../src/app/core/queries/list_users.py)) from a `ListUsersRequest`, then passed straight through the `UserReader` port — see [Core Patterns → Ports and Adapters](../core-patterns/ports-and-adapters.md) for what a port/adapter pair actually is — to whatever adapter implements it. The result, `ListUsersQm` (a `TypedDict` in [`ports/user_reader.py`](../../../../src/app/core/queries/ports/user_reader.py)), bundles the page of `UserQm` results together with `total`/`limit`/`offset` — everything an inbound HTTP handler needs to also emit pagination metadata, without a second round trip.

## Where to go next

- [Domain Entities & Value Objects](domain-entities.md) — the write-side counterpart these models are deliberately *not* shaped like.
- [Database Models (SQLAlchemy Mappings)](database-models.md) — how `SqlaUserReader` builds `UserQm` instances straight from raw SQL columns, bypassing the entity mapping entirely.
- [Use Case Examples → List Users](../use-case-examples/users-list-users.md) — the full request-to-response walkthrough for the use case that returns these models.
