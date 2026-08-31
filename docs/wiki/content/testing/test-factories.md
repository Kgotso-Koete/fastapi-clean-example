# Test Factories

!!! sourcefiles "Relevant Source Files/Folders"
    - [`tests/integration/with_infra/factories.py`](../../../../tests/integration/with_infra/factories.py) — builds real `User` entities through a real, DI (Dependency Injection)-resolved `UserService`
    - [`tests/unit/core/common/services/factories.py`](../../../../tests/unit/core/common/services/factories.py) — the unit-level equivalent, using a `StubPasswordHasher`
    - [`tests/unit/core/common/authorization/factories.py`](../../../../tests/unit/core/common/authorization/factories.py) — a thin, role-flavored wrapper around the services-level factory
    - [`tests/unit/core/common/entities/factories.py`](../../../../tests/unit/core/common/entities/factories.py) — factories for generic test-only entities, unrelated to `User`

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The pattern: sensible-random defaults, explicit overrides

Every factory module in this project follows the same shape: a set of small `create_raw_x()` (or `create_x()`) helper functions, each returning either the caller-supplied value or a freshly generated, collision-safe default (a random UUID (Universally Unique Identifier), a `uuid4().hex`-suffixed username, and so on) — and one or two higher-level `create_user(...)`-style functions that assemble a whole entity (in the Domain-Driven Design sense — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)) out of those helpers, letting any individual field be pinned for a specific test while everything else fills itself in.

!!! figure "How a factory call resolves each field"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        call["create_user(raw_username='alice')"]
        check{"was this field<br/>passed by the caller?"}
        pinned["use 'alice' as given --<br/>needed for THIS test's assertion"]
        random["call create_raw_username() --<br/>uuid4().hex-suffixed default"]
        entity["User entity, built via<br/>UserService.create_user(...)"]

        call --> check
        check -->|yes, this field| pinned --> entity
        check -->|no, other fields| random --> entity

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > Every field on every factory function follows this same `value if value is not None else create_default()` pattern. A test that only cares about, say, whether a duplicate username is rejected can pin `raw_username` and let the email, phone number, and password all generate harmlessly-random, non-colliding defaults — no need to invent a full, realistic-looking user by hand for every single test.

## Two parallel `User`-building tracks: unit vs. integration

There are two independent families of `create_user(...)`-style factories in this codebase, and the difference between them is the whole point: they build the same kind of entity through two different `UserService` instances, one fully in-process and fake, one real and DI-resolved.

!!! figure "Unit-level vs. integration-level User factories"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph unit["tests/unit/core/common/services/factories.py"]
            u_svc["create_user_service()<br/>builds its OWN UserService,<br/>StubPasswordHasher()"]
            u_create["create_user(...)<br/>create_super_user(...)"]
            u_svc --> u_create
        end

        subgraph auth["tests/unit/core/common/authorization/factories.py"]
            a_wrap["make_user() / make_admin()<br/>make_super_admin()<br/>-- role-flavored wrappers"]
        end

        subgraph infra["tests/integration/with_infra/factories.py"]
            i_svc["it_user_service fixture --<br/>REAL UserService, pulled from<br/>the app's own DI container"]
            i_create["create_user(user_service, ...)<br/>create_user_with_password(...)<br/>create_super_admin_with_password(...)"]
            i_svc --> i_create
        end

        u_create --> auth

        linkStyle default stroke-width:3px,stroke:#333333
        style unit stroke-width:1px,stroke:#333333
        style auth stroke-width:1px,stroke:#333333
        style infra stroke-width:1px,stroke:#333333
    ```

- **`tests/unit/core/common/services/factories.py`** never touches a database or the DI container. `create_user_service()` builds a plain `UserService(password_hasher=StubPasswordHasher())` inline, and `create_user(...)`/`create_super_user(...)` call straight into it — the whole thing runs in a single Python process with no I/O. `create_super_user(...)` notably bypasses `UserService.create_user()` for the role field and constructs the `User` entity directly, because `SUPER_ADMIN` is a role `UserService` deliberately refuses to assign through its own public API (Application Programming Interface) (see its docstring: `"System role is not assignable via UserService"`).
- **`tests/unit/core/common/authorization/factories.py`** doesn't duplicate any of that — `make_admin()`/`make_user()` are one-line wrappers calling `create_user(role=UserRole.ADMIN)` / `create_user(role=UserRole.USER)` from the services-level module, and `make_super_admin()` calls `create_super_user()`. It exists purely to give authorization tests role-named entry points (`make_admin()` reads better at a call site checking an admin-only permission than `create_user(role=UserRole.ADMIN)` does), without re-implementing entity construction.
- **`tests/integration/with_infra/factories.py`** takes a `UserService` as its *first parameter* rather than building one — in practice, the real one an integration test resolved out of `it_fastapi_app`'s Dishka container via the `it_user_service` fixture (see [Test Infrastructure & Fixtures](test-infrastructure.md)). `create_user(...)` mirrors the unit-level version's field-by-field defaulting exactly, but every call it makes runs through the real service, the real password hasher configured for the app, and — for `create_user_with_password(...)`/`create_super_admin_with_password(...)` — a real `async def`, since hashing a real password is genuinely awaited work the stub-backed unit factory never needs to be.

The two tracks intentionally look almost identical at the call site (`create_user(raw_username=..., role=...)` in both) — that similarity is what lets a test written against one tier read naturally to someone who just came from the other, even though what's actually running underneath (a stub hasher with no I/O vs. a real hasher behind a real DI container) is entirely different.

## Entity factories outside the `User` family

Not every factory in this codebase is about `User`. [`tests/unit/core/common/entities/factories.py`](../../../../tests/unit/core/common/entities/factories.py) builds small, deliberately generic test-only entities (`NamedEntity`, `NamedEntitySubclass`, `TaggedEntity`) that exist purely to exercise the shared `Entity` base class's own behavior (equality, event collection, etc. — see the base entity's own tests) without needing a real domain concept like `User` in the picture at all:

```python
def create_named_entity(id_: int = 42, name: str = "name") -> NamedEntity:
    return NamedEntity(id_=NamedEntityId(id_), name=name)
```

Here defaults are plain literals (`42`, `"name"`) rather than randomly generated — collision-safety doesn't matter for a throwaway entity whose only job is proving something about the base class, so the simpler literal-default form is used instead of the `create_raw_x()` pattern above.

## Where to go next

- [Test Infrastructure & Fixtures](test-infrastructure.md) — the `it_user_service`/`it_fastapi_app` fixtures that hand `tests/integration/with_infra/factories.py` its real `UserService`.
- [TDD (Test-Driven Development, Red-Green-Refactor)](tdd.md) — how these factories get used inside the RED-then-GREEN test-writing steps this project's plans describe.
- [Domain Entities & Value Objects](../data-models/domain-entities.md) — the real `User` entity and value objects (`Email`, `Username`, `PhoneNumber`, ...) every factory here ultimately constructs.
