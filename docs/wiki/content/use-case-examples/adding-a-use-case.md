# Adding a New Use Case (Command)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/commands/create_user.py`](../../../../src/app/core/commands/create_user.py) — the worked template for this page
    - [`src/app/core/commands/ports/flusher.py`](../../../../src/app/core/commands/ports/flusher.py)
    - [`src/app/core/commands/ports/transaction_manager.py`](../../../../src/app/core/commands/ports/transaction_manager.py)
    - [`src/app/core/commands/ports/user_tx_storage.py`](../../../../src/app/core/commands/ports/user_tx_storage.py)
    - [`src/app/core/commands/ports/utc_timer.py`](../../../../src/app/core/commands/ports/utc_timer.py)
    - [`src/app/core/common/ports/event_dispatcher.py`](../../../../src/app/core/common/ports/event_dispatcher.py)
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py)
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — where `CreateUser` and its ports get wired
    - [`tests/unit/core/common/services/factories.py`](../../../../tests/unit/core/common/services/factories.py) — the factory-function pattern used for unit test fixtures in this codebase

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

A "use case" here is a **Command**: a single class in [`src/app/core/`](../../../../src/app/core/) with one public `execute()` method, that expresses one business operation end to end. [`CreateUser`](../../../../src/app/core/commands/create_user.py) — "an admin creates a new user, possibly an admin, subject to role-management authorization" — is the most complete example already in this codebase, so it's the template this page walks through literally, step by step.

## The layers a new command touches

!!! figure "Which layers change when adding a new command"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph core["core (business rules)"]
            ports["1. Define new ports\n(if none already fit)"]
            cmd["2. Write the command class\n(request/response + execute())"]
            ports --> cmd
        end

        subgraph main["main (composition root)"]
            ioc["3. Wire into CoreProvider\n(main/ioc/core.py)"]
        end

        subgraph tests["tests (unit)"]
            factory["4. Add/extend a factory\n(tests/unit/.../factories.py)"]
            unit["5. Unit test execute()\nwith stubbed ports"]
            factory --> unit
        end

        cmd --> ioc --> unit

        linkStyle default stroke-width:3px,stroke:#333333
        style core fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style main stroke-width:1px,stroke:#333333
        style tests stroke-width:1px,stroke:#333333
    ```

    > The command class itself, and any port it needs that doesn't already exist, live entirely inside `core` — the innermost layer. Wiring a concrete adapter to each port happens only in `main`, the composition root (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what that term means and why the wiring only ever happens there). No `inbound` (HTTP — HyperText Transfer Protocol) work is required at all to add a command — that's a separate, later step, covered by [Adding a New REST Endpoint](adding-a-rest-endpoint.md). A command is usable, and fully unit-testable, before it has any HTTP route pointing at it.

## Step 1 — Reuse or define the ports it needs

[`CreateUser.__init__`](../../../../src/app/core/commands/create_user.py) takes seven collaborators, every one of them a `Protocol` (a port) rather than a concrete class:

```python
def __init__(
    self,
    current_user_service: CurrentUserService,
    user_service: UserService,
    utc_timer: UtcTimer,
    user_tx_storage: UserTxStorage,
    flusher: Flusher,
    transaction_manager: TransactionManager,
    event_dispatcher: EventDispatcher,
) -> None:
```

Most of these already exist and are reused as-is — `UtcTimer`, `Flusher`, `TransactionManager`, `EventDispatcher` are generic enough that almost every command needs them and none are specific to users. [`UserTxStorage`](../../../../src/app/core/commands/ports/user_tx_storage.py) is the one port specific to this command's aggregate (a Domain-Driven Design term for a cluster of related objects — here just `User` — treated as one consistency boundary, with a single entity as its root) — it only declares `add()` and `get_by_id()`, exactly what `CreateUser` needs, nothing more:

```python
class UserTxStorage(Protocol):
    """Transactional: commit required."""

    @abstractmethod
    def add(self, user: User) -> None: ...

    @abstractmethod
    async def get_by_id(self, user_id: UserId, *, for_update: bool = False) -> User | None: ...
```

When your new command needs to read or write a kind of data no existing port covers, define a new, narrowly-scoped `Protocol` next to the others under `core/commands/ports/` (or `core/queries/ports/` for a read-only query) — one method per real need, not a general-purpose repository interface. This is the Ports-and-Adapters pattern covered in more depth on [Core Patterns → Ports and Adapters](../core-patterns/ports-and-adapters.md): `core` only ever describes *what* it needs; concrete adapters that satisfy the port live in [`outbound/`](../../../../src/app/outbound/).

## Step 2 — Write the command class

`CreateUser` follows a consistent shape every command in this codebase repeats:

1. **A frozen `@dataclass` request** (`CreateUserRequest`) — the input, decoupled from any HTTP schema.
2. **A response type** (`CreateUserResponse`, here a `TypedDict`) — the output.
3. **The command class itself**, holding only its injected ports as private attributes, with a docstring stating its authorization rules in plain English (this docstring is later reused verbatim as the OpenAPI route description — see [Adding a New REST Endpoint](adding-a-rest-endpoint.md)).
4. **One [`execute()`](../../../../src/app/core/commands/create_user.py) method** that, in order: resolves the current user, authorizes the operation, validates/parses input into value objects (small, immutable types defined purely by their value, like `Username` or `Email` — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)), performs the business operation via a domain service, stages any resulting domain events, flushes to catch uniqueness/constraint violations early, commits, then dispatches the already-staged events:

```python
async def execute(self, request: CreateUserRequest) -> CreateUserResponse:
    current_user = await self._current_user_service.get_current_user()
    role = UserRole(request.role)
    authorize(CanManageRole(), context=RoleManagementContext(subject=current_user, target_role=role))

    username = Username(request.username)
    password = RawPassword(request.password)
    email = Email(request.email)
    phone_number = PhoneNumber(request.phone_number)

    user = await self._user_service.create_user_with_raw_password(
        user_id=create_user_id(), username=username, email=email, phone_number=phone_number,
        raw_password=password, now=self._utc_timer.now, role=role,
    )
    self._user_tx_storage.add(user)
    events = user.collect_events()
    await self._event_dispatcher.stage(events)  # BEFORE flush()/commit()
    await self._flusher.flush()                 # may raise *AlreadyExistsError
    await self._transaction_manager.commit()
    await self._event_dispatcher.dispatch(events)  # AFTER commit()
    return CreateUserResponse(id=user.id_, created_at=user.created_at.value)
```

The `stage()` → `flush()` → `commit()` → `dispatch()` ordering is not arbitrary — `stage()` must run before the transaction commits so background-dispatched events land in the same transactional outbox row as the state change, and `dispatch()` must run only after commit succeeds so a failed transaction never fires a domain event for something that didn't actually happen. See [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) for the full mechanism this protects.

## Step 3 — Wire it into the composition root

`CoreProvider` in [`main/ioc/core.py`](../../../../src/app/main/ioc/core.py) is where every command, query, and port gets bound to a concrete implementation via [Dishka](../core-patterns/dependency-injection.md). Adding `CreateUser` was a single line under the `# Commands` section:

```python
# Commands
create_user = provide(CreateUser)
```

Dishka resolves `CreateUser.__init__`'s other parameters by type from whatever else `CoreProvider` (or another provider in the same container) already provides — `user_service`, `utc_timer`, `user_tx_storage`, `flusher`, `tx_manager`, and `event_dispatcher` are all already bound a few lines earlier in the same file. If your new command needs a genuinely new port, add its own `provide(...)` line binding that port to a concrete adapter (written in `outbound/`) alongside it — nothing else in `CoreProvider` needs to change.

## Step 4 — Unit-test it with a factory

This codebase's unit tests build their fixtures with small, composable **factory functions** rather than fixture classes or hardcoded literals — see [`tests/unit/core/common/services/factories.py`](../../../../tests/unit/core/common/services/factories.py), which `CreateUser`'s own domain service (`UserService`) is tested against in [`tests/unit/core/common/services/test_user.py`](../../../../tests/unit/core/common/services/test_user.py):

```python
def create_username(value: str | None = None) -> Username:
    default = f"user_{uuid.uuid4().hex[:8]}"
    return Username(value if value is not None else default)

def create_user_service(password_hasher: PasswordHasher | None = None) -> UserService:
    return UserService(password_hasher=password_hasher if password_hasher is not None else StubPasswordHasher())
```

Each factory takes every field as an optional override with a sensible random default — a test only has to specify the one or two fields it actually cares about. Following this same pattern for a new command means: a small `factories.py` alongside its test module, one `create_<x>()` per value object/port your command's `execute()` takes, and a stub or mock implementing each `Protocol` port (see [Test Factories](../testing/test-factories.md) and [Test Infrastructure & Fixtures](../testing/test-infrastructure.md) for the stub/mock conventions used elsewhere in this suite). A unit test for a command then constructs the command directly with stubbed ports — no database, no HTTP, no container — and asserts on `execute()`'s return value and the state of its stubs (e.g. "was `add()` called with the right user", "were the right events staged").

## Where to go next

- [Adding a New REST Endpoint](adding-a-rest-endpoint.md) — the next step once a command exists: exposing it over HTTP.
- [Core Patterns → Ports and Adapters](../core-patterns/ports-and-adapters.md) — the pattern behind every port a command depends on.
- [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) — why `stage()`/`dispatch()` are ordered the way they are.
