# Database Models (SQLAlchemy Mappings)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/outbound/persistence_sqla/mappings/all.py`](../../../../src/app/outbound/persistence_sqla/mappings/all.py) — `map_tables()`, the single entry point that wires every mapping at startup
    - [`src/app/outbound/persistence_sqla/mappings/user.py`](../../../../src/app/outbound/persistence_sqla/mappings/user.py) — `users_table` + `map_users_table()`
    - [`src/app/outbound/persistence_sqla/mappings/auth_session.py`](../../../../src/app/outbound/persistence_sqla/mappings/auth_session.py) — `auth_sessions_table` + `map_auth_sessions_table()`
    - [`src/app/outbound/persistence_sqla/mappings/outbox_message.py`](../../../../src/app/outbound/persistence_sqla/mappings/outbox_message.py) — `event_outbox_table` + `map_event_outbox_table()`
    - [`src/app/outbound/persistence_sqla/registry.py`](../../../../src/app/outbound/persistence_sqla/registry.py) — the shared `MetaData`/`registry` every mapping registers into
    - [`src/app/outbound/persistence_sqla/constraint_names.py`](../../../../src/app/outbound/persistence_sqla/constraint_names.py) — named constants for the unique constraints Alembic/SQLAlchemy generate
    - [`src/app/outbound/adapters/sqla_user_tx_storage.py`](../../../../src/app/outbound/adapters/sqla_user_tx_storage.py) — the adapter that reads/writes `User` entities through this mapping
    - [`src/app/outbound/adapters/sqla_user_reader.py`](../../../../src/app/outbound/adapters/sqla_user_reader.py) — the adapter that builds `UserQm` query models straight from the same table

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The mapping style: imperative, not declarative — and there's no separate model class

The obvious way to add SQLAlchemy to a project is Declarative Mapping: define a `class UserModel(Base): __tablename__ = "users"; id: Mapped[UUID] = ...` (UUID here is short for Universally Unique Identifier) and treat that as the "database model," separate from the domain entity. **This codebase does not do that.** There is no `UserModel` class anywhere. Instead, `map_users_table()` in [`mappings/user.py`](../../../../src/app/outbound/persistence_sqla/mappings/user.py) uses **Imperative (Classical) Mapping** — see [Outbound Layer → Persistence: imperative SQLAlchemy mappings](../architecture/outbound-layer.md#persistence-imperative-sqlalchemy-mappings) for the general declarative-vs-imperative distinction this specializes — `mapper_registry.map_imperatively(User, users_table, properties={...})` — to map the columns of a plain `sqlalchemy.Table` object directly onto the `User` entity class itself, the exact same `User` documented in [Domain Entities & Value Objects](domain-entities.md).

Here is the mapping call itself, verbatim, from [`mappings/user.py`](../../../../src/app/outbound/persistence_sqla/mappings/user.py):

```python
def map_users_table() -> None:
    mapper_registry.map_imperatively(
        User,
        users_table,
        properties={
            "id_": users_table.c.id,
            "username": composite(Username, users_table.c.username),
            "email": composite(Email, users_table.c.email),
            "phone_number": composite(PhoneNumber, users_table.c.phone_number),
            "password_hash": users_table.c.password_hash,
            "role": users_table.c.role,
            "is_active": users_table.c.is_active,
            "_created_at": composite(UtcDatetime, users_table.c.created_at),
            "updated_at": composite(UtcDatetime, users_table.c.updated_at),
        },
        column_prefix="__",
    )
```

This is the reason `map_tables()` exists as an explicit startup call at all (see [`mappings/all.py`](../../../../src/app/outbound/persistence_sqla/mappings/all.py)'s own docstring): with declarative mapping, defining the model class does the mapping implicitly, just by inheriting `Base`. With imperative mapping, nothing links `User` to `users_table` until `map_imperatively()` actually runs — so something has to call it once, deliberately, before any query touches `User`. That "something" is `map_tables()`, called both from the app's composition root (see [Main (Composition Root)](../architecture/main-composition-root.md) — the one place that wires every concrete class together) and from Alembic's `env.py`, guarded by `if mapper_registry.mappers: return` so it's safe to call more than once.

!!! figure "Imperative mapping: two independent definitions, joined by one call"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph core["core/common/entities/user.py"]
            User["class User(Entity[UserId])\nknows nothing about SQL"]
        end

        subgraph outbound["outbound/persistence_sqla/mappings/user.py"]
            table["users_table = Table(...)\nplain columns, no class"]
            mapfn["map_users_table()"]
        end

        table --> mapfn
        User -.->|"map_imperatively(User, users_table, properties)"| mapfn
        mapfn --> mapped["User is now ORM-mapped\n(session.add/get/select all work on it)"]

        linkStyle default stroke-width:3px,stroke:#333333
        style core stroke-width:1px,stroke:#333333
        style outbound stroke-width:1px,stroke:#333333
    ```

    > This is what "Clean Architecture" buys concretely here: `User` (inner layer) has zero SQLAlchemy imports and zero knowledge that a `users_table` exists. `users_table` and the mapping call (outer layer, `outbound/`) import *inward* to reach `User`, never the other way — the same one-directional import rule covered in [Architecture → Layer Dependencies & Import Rules](../architecture/layer-dependencies.md). Once `map_users_table()` has run, `User` behaves like any class mapped by an ORM (Object-Relational Mapping) for the rest of the app's lifetime: `session.add(user)`, `session.get(User, user_id)`, and `select(User)` all work directly on it (see [`sqla_user_tx_storage.py`](../../../../src/app/outbound/adapters/sqla_user_tx_storage.py)) — there's no separate "convert the database row into a domain object" step to write or maintain, because the mapped class and the domain class are literally the same object.

## `composite()`: value objects reconstructed automatically

Four of `User`'s fields — `username`, `email`, `phone_number`, and both `UtcDatetime` timestamps — are value objects, not primitive columns. SQLAlchemy's `composite()` is what makes that transparent: each maps a single database column onto a value-object field by calling the value object's constructor with the column's raw value, and unwraps it back to the raw value on the way to a write. `composite(Username, users_table.c.username)` means: on load, call `Username(row_value)` — running that value object's own validation and normalization — and store the result on `user.username`; on save, read `user.username.value` back out. This is also why `column_prefix="__"` appears on every mapping in this file: SQLAlchemy needs a way to store the *raw* column value internally alongside the composite's reconstructed value-object instance, and the prefix keeps that internal attribute out of the way of the real one.

`password_hash`, `role`, and `is_active` map directly to their columns with no `composite()` wrapper, because they aren't value objects on the entity — `password_hash` is a `NewType`-tagged `bytes`, `role` is a plain `UserRole` `StrEnum` (mapped via a non-native SQLAlchemy `Enum` so the column stores it as a comparable string, not a Postgres-native enum type), and `is_active` is a plain `bool`.

## The other two mappings, and the shared registry

[`auth_sessions_table`](../../../../src/app/outbound/persistence_sqla/mappings/auth_session.py) and [`event_outbox_table`](../../../../src/app/outbound/persistence_sqla/mappings/outbox_message.py) follow the identical pattern — a plain `Table`, a `map_*_table()` function calling `map_imperatively()`, `composite()` for their own `UtcDatetime` fields (`expiration` on `AuthSession`, none needed on `OutboxMessage` beyond its own timestamps which stay as plain `DateTime` columns) — mapped onto `AuthSession` and `OutboxMessage` respectively, both of which live in `outbound/` themselves rather than `core/` (session and outbox tracking are infrastructure concerns, not domain entities). `auth_sessions_table.user_id` is a real foreign key to `users.id` with `ondelete="CASCADE"`, so deleting a user cleans up their sessions at the database level.

All three mappings share one [`registry.py`](../../../../src/app/outbound/persistence_sqla/registry.py): a single `MetaData` (carrying the project's naming convention for indexes/constraints/foreign keys — the same convention that produces the exact names in [`constraint_names.py`](../../../../src/app/outbound/persistence_sqla/constraint_names.py), like `uq_users_username`) and a single `mapper_registry` built from it. Every `Table` in every mapping file registers into this same `MetaData`, which is what lets Alembic autogenerate migrations that see the whole schema at once, and is why [`mappings/all.py`](../../../../src/app/outbound/persistence_sqla/mappings/all.py)'s `map_tables()` calls all three `map_*_table()` functions from one place.

## Three representations of "a user," and how they connect

Between this page and the previous two, a `User` in this codebase now exists in three genuinely different shapes, used for three different purposes:

!!! figure "Entity, database mapping, and query model: three shapes, one underlying user"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph domain["core/common/entities/user.py"]
            entity["User entity\nid_, VOs, mutable, records events"]
        end

        subgraph db["outbound/persistence_sqla"]
            table["users_table\n(plain SQL columns)"]
        end

        subgraph readmodel["core/queries/models/user.py"]
            qm["UserQm\nflat DTO, plain types, no behavior"]
        end

        entity <-->|"map_imperatively()\nsame class, ORM-mapped in place"| table
        table -->|"SqlaUserReader:\nSELECT columns, UserQm(...)"| qm

        linkStyle default stroke-width:3px,stroke:#333333
        style domain stroke-width:1px,stroke:#333333
        style db stroke-width:1px,stroke:#333333
        style readmodel stroke-width:1px,stroke:#333333
    ```

- **`User` (entity)** — [Domain Entities & Value Objects](domain-entities.md). The only one with identity, mutation, invariants, and event recording. Used on the command/write side.
- **`users_table` mapping** — this page. Not a separate class at all; it's the same `User` class made persistable, via imperative mapping rather than a parallel model. [`SqlaUserTxStorage`](../../../../src/app/outbound/adapters/sqla_user_tx_storage.py) reads and writes real `User` instances through it with no manual conversion step in either direction.
- **`UserQm` (query model)** — a DTO (Data Transfer Object); see [Query Models (DTOs)](query-models.md). Never touches the mapped `User` class at all. [`SqlaUserReader.list_users`](../../../../src/app/outbound/adapters/sqla_user_reader.py) issues its own `select(users_table.c.id, users_table.c.username, ...)` against the raw table columns and builds `UserQm(...)` directly from the result rows — bypassing entity reconstruction entirely, since the read side has no use for value-object validation or mutation machinery on data it's only going to serialize back out.

The adapter code that "converts" between these representations is, concretely: nothing, for entity ↔ table (the mapping itself *is* the conversion, applied once at startup); and a plain dataclass constructor call, for table → query model (`UserQm(id=row.id, username=row.username, ...)` in `sqla_user_reader.py`). There is deliberately no adapter that converts `User` → `UserQm` directly — the query side always goes straight to the table.

## Where to go next

- [Domain Entities & Value Objects](domain-entities.md) — the `User` entity these mappings attach to.
- [Query Models (DTOs)](query-models.md) — the flatter shape `SqlaUserReader` builds from this same table.
- [Development Guide → Database Migrations](../development-guide/database-migrations.md) — how Alembic autogenerates migrations from this same `MetaData`/`registry`.
