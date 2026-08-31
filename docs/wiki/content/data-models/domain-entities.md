# Domain Entities & Value Objects

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/common/entities/base.py`](../../../../src/app/core/common/entities/base.py) — the `Entity` base class: identity, mutability, event recording
    - [`src/app/core/common/entities/user.py`](../../../../src/app/core/common/entities/user.py) — the `User` entity itself
    - [`src/app/core/common/entities/types_.py`](../../../../src/app/core/common/entities/types_.py) — `UserId`, `UserPasswordHash`, `UserRole`
    - [`src/app/core/common/value_objects/base.py`](../../../../src/app/core/common/value_objects/base.py) — the `ValueObject` base class
    - [`src/app/core/common/value_objects/email.py`](../../../../src/app/core/common/value_objects/email.py) — `Email`
    - [`src/app/core/common/value_objects/phone_number.py`](../../../../src/app/core/common/value_objects/phone_number.py) — `PhoneNumber`
    - [`src/app/core/common/value_objects/username.py`](../../../../src/app/core/common/value_objects/username.py) — `Username`
    - [`src/app/core/common/value_objects/raw_password.py`](../../../../src/app/core/common/value_objects/raw_password.py) — `RawPassword`
    - [`src/app/core/common/value_objects/utc_datetime.py`](../../../../src/app/core/common/value_objects/utc_datetime.py) — `UtcDatetime`
    - [`src/app/core/common/events/domain_event.py`](../../../../src/app/core/common/events/domain_event.py) — the `DomainEvent` base class that `collect_events()` returns instances of

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Two kinds of object, one distinction

Everything under `src/app/core/common/` that models "a thing in the domain" is either an **Entity** or a **Value Object**, and the codebase draws the line in exactly one place: how equality works.

- An **Entity** ([`base.py`](../../../../src/app/core/common/entities/base.py)) is compared by its `id_` alone. Two `User` instances with the same `id_` are the *same* user even if every other field differs — because one of them is a stale read and the other reflects a later update. Identity, not attribute values, is what makes them "the same thing."
- A **Value Object** ([`value_objects/base.py`](../../../../src/app/core/common/value_objects/base.py)) has no identity at all — it *is* its attributes. `Email("a@b.com") == Email("a@b.com")` is `True` because `ValueObject` is a frozen `@dataclass`, and dataclasses generate structural `__eq__` for free. There's nothing to compare but the value.

!!! figure "Entity vs. Value Object: what makes them equal"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph entity["Entity (base.py)"]
            e1["id_ = UUID(...)"]
            e2["mutable fields"]
            eeq["__eq__ compares id_ only"]
        end

        subgraph vo["ValueObject (value_objects/base.py)"]
            v1["frozen dataclass fields"]
            veq["__eq__ compares all fields (dataclass-generated)"]
        end

        e1 --> eeq
        e2 -.->|"ignored by equality"| eeq
        v1 --> veq

        linkStyle default stroke-width:3px,stroke:#333333
        style entity stroke-width:1px,stroke:#333333
        style vo stroke-width:1px,stroke:#333333
    ```

    > This diagram shows the actual mechanism, not just the label: `Entity.__eq__` (`base.py:45-50`) explicitly discards every field except `id_` when comparing, while `ValueObject` never overrides `__eq__` at all — it relies on `@dataclass(frozen=True, slots=True)` generating one from every field. A `User` can have its `role` or `email` change over its lifetime and still be recognized as the same user; an `Email` with one character different is, definitionally, a different `Email`.

## `Entity`: identity, controlled mutation, and event recording

[`Entity[T: Hashable]`](../../../../src/app/core/common/entities/base.py) is a generic base class parameterized on the type of its id (`User` is `Entity[UserId]`, where `UserId = NewType("UserId", UUID)` — UUID (Universally Unique Identifier) is Python's standard 128-bit identifier type). Three mechanisms worth calling out, all in a class that is otherwise a thin ~60 lines:

- **`id_` is write-once.** `__setattr__` is overridden so that any attempt to reassign `id_` after it's already set raises `AttributeError`. Every other attribute can be freely reassigned — entities are mutable by design, just not in their identity.
- **`__new__` blocks direct instantiation of the base class.** `Entity` itself isn't meant to be used — only concrete subclasses like `User` — so `Entity()` raises `TypeError` before `__init__` ever runs.
- **Event recording is a queue, not a side channel.** `record_event(event)` appends a `DomainEvent` to a private `_events` list; `collect_events()` returns a copy of that list and clears it in the same call. This is the entity's only public way to communicate "something worth telling the rest of the system happened" — it never dispatches or publishes anything itself, it just remembers.

Here is the whole mechanism, verbatim, from [`entities/base.py`](../../../../src/app/core/common/entities/base.py):

```python
def record_event(self, event: DomainEvent) -> None:
    """Record a domain event. Events are collected after the use case commits."""
    self._events.append(event)

def collect_events(self) -> list[DomainEvent]:
    """Return and clear all recorded events. Call after transaction commit."""
    events = self._events.copy()
    self._events.clear()
    return events
```

The intent, stated in the docstring, is a strict ordering: a use case mutates the entity (which internally calls `record_event`), persists the change, and only *then* calls `collect_events()` — turning "events that happened during this unit of work" into a value it can hand off for dispatch, with no risk of an event escaping before its cause is durably committed. [`create_user.py`](../../../../src/app/core/commands/create_user.py) shows the real sequence: `self._user_tx_storage.add(user)` persists the new `User`, then `events = user.collect_events()` immediately after, then `await self._event_dispatcher.stage(events)`. The full dispatch story — sync vs. background handlers, the transactional outbox — is covered in [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md); this page only covers where events come from.

## `ValueObject`: pure value, validated at construction

[`ValueObject`](../../../../src/app/core/common/value_objects/base.py) is a frozen (`frozen=True, slots=True`) dataclass base. Every concrete value object in this codebase follows the same shape: validate the raw input in `__init__` or `__post_init__`, normalize it if needed, and store the result with `object.__setattr__` (the only way to set an attribute on a frozen dataclass from inside its own `__init__`). Once constructed, it cannot be mutated — any "change" means constructing a new instance.

| Value Object | Validates / normalizes | Example |
|---|---|---|
| [`Email`](../../../../src/app/core/common/value_objects/email.py) | strips + lowercases, enforces max length and a regex shape | `Email("A@Example.COM")` → stored as `"a@example.com"` |
| [`PhoneNumber`](../../../../src/app/core/common/value_objects/phone_number.py) | strips all non-digits, accepts leading `0` or `+27`, normalizes to `27XXXXXXXXX` | `PhoneNumber("083 123 4567")` → stored as `"27831234567"` |
| [`Username`](../../../../src/app/core/common/value_objects/username.py) | length bounds, allowed alphabet, no leading/trailing/consecutive specials | rejects `"..bad--name.."` |
| [`RawPassword`](../../../../src/app/core/common/value_objects/raw_password.py) | minimum length, then encodes to `bytes` | never stored as plaintext beyond this object's lifetime |
| [`UtcDatetime`](../../../../src/app/core/common/value_objects/utc_datetime.py) | rejects naive datetimes, normalizes any timezone to UTC (Coordinated Universal Time) | orderable via `@total_ordering` + `__lt__` |

> Every one of these raises `BusinessTypeError` (not a generic `ValueError`) on invalid input — a domain-specific exception type that inbound adapters can catch and translate into an HTTP (Hypertext Transfer Protocol) 4xx, without the core layer knowing HTTP exists. That translation lives in the inbound layer, not here; see [Architecture → Inbound Layer](../architecture/inbound-layer.md).

`ValueObject.__new__` also guards two misuse cases: instantiating the bare `ValueObject` base directly, and defining a subclass dataclass with zero fields (a value object that carries no value isn't a value object). The custom `__repr__` is a privacy mechanism, not cosmetic — fields marked `repr=False` (like `RawPassword.value`) are omitted from `repr()` output entirely, so a stray `print(user)` or log line can't leak a password hash or hashed secret by accident.

## The `User` entity: composition in practice

`User` is the one entity currently in this codebase, and it shows the pattern in full: an `id_` plus a mix of value objects and plain fields.

!!! figure "User entity: fields and their types"
    ```mermaid
    classDiagram
        class User {
            +UserId id_
            +Username username
            +Email email
            +PhoneNumber phone_number
            +UserPasswordHash password_hash
            +UserRole role
            +bool is_active
            +UtcDatetime created_at
            +UtcDatetime updated_at
            +record_event(event)
            +collect_events() list~DomainEvent~
        }
        class Entity~T~ {
            +T id_
            +record_event(event)
            +collect_events() list~DomainEvent~
        }
        class Username {
            +str value
        }
        class Email {
            +str value
        }
        class PhoneNumber {
            +str value
        }
        class UtcDatetime {
            +datetime value
        }
        class UserRole {
            <<enumeration>>
            SUPER_ADMIN
            ADMIN
            USER
        }
        Entity~T~ <|-- User
        User *-- Username
        User *-- Email
        User *-- PhoneNumber
        User *-- UserRole
        User *-- UtcDatetime : created_at, updated_at
    ```

    > `User` (in [`user.py`](../../../../src/app/core/common/entities/user.py)) subclasses `Entity[UserId]` and composes four value objects (`Username`, `Email`, `PhoneNumber`, `UtcDatetime` used twice, for `created_at` and `updated_at`) plus two plain-typed fields that aren't value objects: `password_hash` (a `NewType`-tagged `bytes`, not a validated shape — validation of the *raw* password happens earlier, in `RawPassword`) and `role` (a plain `StrEnum`, `UserRole`, since role membership doesn't need the validate-and-normalize machinery a value object provides). `created_at` is deliberately read-only from outside — it's stored as `_created_at` and exposed only via a `@property` with no setter, since a user's creation timestamp should never change after construction, even though nothing at the `Entity`/`ValueObject` base-class level enforces that; it's a convention applied at the `User` class itself.

`UserRole` also carries one small piece of business logic beyond being a plain enum: `is_system`, a property that's `True` only for `SUPER_ADMIN` — used elsewhere in the authorization code to keep the bootstrap superadmin role from being granted or revoked like an ordinary admin role.

## Where to go next

- [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) — what happens to the events `collect_events()` returns.
- [Data Models → Database Models (SQLAlchemy Mappings)](database-models.md) — how this same `User` entity is mapped directly onto a table, with no separate ORM (Object-Relational Mapping) model class.
- [Data Models → Query Models (DTOs)](query-models.md) — the flatter, read-only shape (a DTO, or Data Transfer Object) a `User` takes on the query side.
