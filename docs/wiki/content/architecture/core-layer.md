# Core Layer (Domain & Business Rules)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/common/entities/`](../../../../src/app/core/common/entities/) — `Entity` base class, `User`
    - [`src/app/core/common/value_objects/`](../../../../src/app/core/common/value_objects/) — `ValueObject` base class, `Email`, `Username`, `RawPassword`, `UtcDatetime`, `PhoneNumber`
    - [`src/app/core/common/ports/`](../../../../src/app/core/common/ports/) — abstract interfaces `core` depends on but never implements
    - [`src/app/core/common/events/`](../../../../src/app/core/common/events/) — `DomainEvent`, `UserRegisteredEvent`, `SendWelcomeEmail` handler
    - [`src/app/core/common/authorization/`](../../../../src/app/core/common/authorization/) — `Permission`, `CurrentUserService`, role hierarchy
    - [`src/app/core/common/factories/id_factory.py`](../../../../src/app/core/common/factories/id_factory.py) — `create_user_id()`
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService`
    - [`src/app/core/commands/`](../../../../src/app/core/commands/) — write use cases (`CreateUser`, `GrantAdmin`, …) and their ports
    - [`src/app/core/queries/`](../../../../src/app/core/queries/) — read use cases (`ListUsers`) and their ports

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What lives here

`core` is the innermost ring in [Layer Dependencies & Import Rules](layer-dependencies.md) — the layer that may not import `inbound`, `outbound`, or `main` at all. Everything under `src/app/core/` is pure business logic: entities, value objects, ports, domain events, authorization rules, and the use cases (commands/queries) that orchestrate them. Nothing in this layer imports SQLAlchemy, FastAPI, or Celery.

!!! figure "core's internal module structure"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph common["core.common"]
            entities(["entities"])
            vos(["value_objects"])
            ports(["ports"])
            events(["events"])
            authz(["authorization"])
            services(["services"])
            factories(["factories"])
        end
        subgraph commands["core.commands"]
            cmd_uc(["CreateUser, GrantAdmin, …"])
            cmd_ports(["ports: Flusher, TransactionManager, …"])
        end
        subgraph queries["core.queries"]
            qry_uc(["ListUsers"])
            qry_ports(["ports: UserReader"])
        end

        cmd_uc --> common
        cmd_uc --> cmd_ports
        qry_uc --> common
        qry_uc --> qry_ports

        linkStyle default stroke-width:3px,stroke:#333333
        style common fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style commands stroke-width:1px,stroke:#333333
        style queries stroke-width:1px,stroke:#333333
    ```

    > Both `core.commands` and `core.queries` depend on shared building blocks in `core.common`, but never on each other — enforced by the CQRS (Command Query Responsibility Segregation) forbidden-import contracts described in [Layer Dependencies & Import Rules](layer-dependencies.md#the-cqrs-split-and-the-auth-ctx-boundary). Each use case also declares its own narrow ports (e.g. `commands.ports.transaction_manager.TransactionManager`, `queries.ports.user_reader.UserReader`) rather than reaching into the other side's ports.

## Entities and value objects

[`Entity`](../../../../src/app/core/common/entities/base.py) is the base class for anything with an identity that persists across mutation — `User` is the only concrete entity in this codebase today. It's generic over its id type (`Entity[T: Hashable]`), compares equal purely by `id_` (never by other attributes), and forbids reassigning `id_` once set:

```python
class Entity[T: Hashable]:
    _events: list[DomainEvent]

    def __init__(self, *, id_: T) -> None:
        self.id_ = id_
        object.__setattr__(self, "_events", [])

    def record_event(self, event: DomainEvent) -> None:
        """Record a domain event. Events are collected after the use case commits."""
        self._events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        """Return and clear all recorded events. Call after transaction commit."""
        ...
```

`record_event`/`collect_events` are how an entity accumulates domain events during a use case (e.g. `User.create` recording a `UserRegisteredEvent`) without the entity itself knowing anything about how those events eventually get dispatched — see [`docs/wiki/content/core-patterns/domain-events-outbox.md`](../core-patterns/domain-events-outbox.md).

[`ValueObject`](../../../../src/app/core/common/value_objects/base.py) is the base for anything defined purely by its own immutable data — `Email`, `Username`, `RawPassword`, `PhoneNumber`, `UtcDatetime`. Each is a frozen, slotted dataclass that validates its own invariants in `__post_init__` (or a custom `__init__`, for types like `Email` that need to normalize the value before validating it) and raises `BusinessTypeError` on violation. `Email`, for instance, lowercases and strips its input, then validates length and format against a compiled regex — construction itself is the only place that check ever needs to happen; every other piece of code that holds an `Email` instance can trust it's already valid.

## Ports: what core depends on, never implements

A port is a plain `Protocol` (or in a couple of legacy-shaped classes, an ABC, short for Abstract Base Class) describing a capability `core` needs, with zero knowledge of how it's fulfilled. [`src/app/core/common/ports/`](../../../../src/app/core/common/ports/) holds the layer-wide ones:

| Port | What it abstracts |
|---|---|
| `PasswordHasher` | hash/verify a raw password |
| `IdentityProvider` | resolve the current caller's `UserId` |
| `AccessRevoker` | revoke all of a user's active sessions |
| `EmailSender` | send an email |
| `EventDispatcher` | stage/dispatch domain events |
| `EventHandler[T]` | handle one event type, declaring its own `DISPATCH_MODE` (`"sync"` or `"background"`) |

> `core.commands` and `core.queries` each additionally declare their own, narrower ports under `commands/ports/` and `queries/ports/` — `TransactionManager`, `Flusher`, `UserTxStorage`, `UtcTimer`, `OutboxRepository` for commands; `UserReader` for queries. None of these ports import anything from `outbound` — the concrete adapters that implement them (`SqlaTransactionManager`, `BcryptPasswordHasher`, …) live in [`outbound`](outbound-layer.md) and are wired in only by [`main`](main-composition-root.md).

## Commands vs. queries: the CQRS split

`core.commands` holds every use case that changes state — `CreateUser`, `ActivateUser`, `DeactivateUser`, `GrantAdmin`, `RevokeAdmin`, `SetUserPassword`. `core.queries` holds read-only use cases — currently just `ListUsers`. Each command/query follows the same shape: a frozen `*Request` dataclass, a class with an `execute()` method, and constructor-injected ports plus services.

[`CreateUser.execute()`](../../../../src/app/core/commands/create_user.py) is a representative write use case:

```python
async def execute(self, request: CreateUserRequest) -> CreateUserResponse:
    current_user = await self._current_user_service.get_current_user()
    role = UserRole(request.role)
    authorize(CanManageRole(), context=RoleManagementContext(subject=current_user, target_role=role))
    ...
    user = await self._user_service.create_user_with_raw_password(...)
    self._user_tx_storage.add(user)
    events = user.collect_events()
    await self._event_dispatcher.stage(events)      # BEFORE flush/commit
    await self._flusher.flush()                       # surfaces uniqueness violations
    await self._transaction_manager.commit()
    await self._event_dispatcher.dispatch(events)      # AFTER commit
```

The `stage()`-before-`flush()`/`commit()`, `dispatch()`-after-`commit()` ordering is the transactional-outbox contract every command that raises events follows — see [Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) for why the ordering matters. `ListUsers.execute()` (the one query) is simpler: authorize, then delegate straight to `UserReader.list_users()` — no transaction manager, no flusher, no events, since a read never mutates anything.

## Domain events

[`DomainEvent`](../../../../src/app/core/common/events/domain_event.py) is a frozen dataclass base with one required field (`occurred_at`) and two methods, `to_payload()`/`from_payload()`, that (de)serialize a concrete event to/from a plain JSON (JavaScript Object Notation)-safe dict — this is what lets an event cross the wire as a Celery message body without ever pickling a Python object. `UserRegisteredEvent` is the one concrete event today, raised by `UserService.create_user()` whenever a new `User` is constructed. `SendWelcomeEmail` is its one registered handler, declaring `DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "background"` — meaning it always goes through the outbox rather than blocking the request that raised it.

## Authorization

[`authorization/`](../../../../src/app/core/common/authorization/) implements a small, composable permission system: `Permission[PC]` is an ABC with one method, `is_satisfied_by(context: PC) -> bool`; `authorize(permission, context=...)` raises `AuthorizationError` if not satisfied. Concrete permissions (`CanManageSelf`, `CanManageSubordinate`, `CanManageRole`) each check a `PermissionContext` subclass carrying exactly the data that permission needs — e.g. `RoleManagementContext(subject, target_role)`. `ROLE_HIERARCHY` is a plain `Mapping[UserRole, set[UserRole]]` (`SUPER_ADMIN` manages `ADMIN`/`USER`; `ADMIN` manages `USER` only) that `CanManageRole`/`CanManageSubordinate` consult. `CurrentUserService.get_current_user()` ties this together with the `IdentityProvider`/`AccessRevoker` ports: it resolves the current user, and if that user no longer exists or has been deactivated, proactively revokes all their sessions before raising `AuthorizationError` — a defense against a still-valid session cookie outliving the account it belongs to.

## Where to go next

- [Layer Dependencies & Import Rules](layer-dependencies.md) — the enforced contracts that keep `core.commands`/`core.queries`/`core.common` from leaking into each other.
- [Outbound Layer (Infrastructure Adapters)](outbound-layer.md) — the concrete classes that implement every port described above.
- [Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) — the full stage/dispatch/outbox mechanism `UserRegisteredEvent` flows through.
