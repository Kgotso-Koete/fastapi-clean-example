# Users: Create User

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/create_user.py`](../../../../src/app/inbound/http/users/create_user.py) — HTTP router
    - [`src/app/core/commands/create_user.py`](../../../../src/app/core/commands/create_user.py) — the `CreateUser` command
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.create_user_with_raw_password()`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`
    - [`src/app/core/common/authorization/role_hierarchy.py`](../../../../src/app/core/common/authorization/role_hierarchy.py) — `ROLE_HIERARCHY`
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — uniqueness errors
    - [`src/app/outbound/adapters/sqla_flusher.py`](../../../../src/app/outbound/adapters/sqla_flusher.py) — translates DB unique-constraint violations into those errors
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`POST /users/` lets an already-authenticated admin create a new user account directly — as opposed to [Account: Sign Up](account-sign-up.md), which is the public, unauthenticated self-registration path. The caller picks the new account's initial role (`user` or `admin`), and the command enforces who is allowed to hand out which role before anything is written.

`CreateUser`'s own docstring states this plainly:

- Open to admins.
- Creates new user, including admins, if the username is unique.
- Only super admins can create new admins.

## Request flow

!!! figure-wide "POST /users/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as create_user router
        participant Cmd as CreateUser.execute()
        participant Authz as authorize(CanManageRole)
        participant Svc as UserService
        participant Storage as UserTxStorage (port)
        participant Events as EventDispatcher (port)
        participant Flush as Flusher (port)
        participant Tx as TransactionManager (port)

        Client->>Router: POST /users/ {username, email, phone_number, password, role}
        Router->>Cmd: execute(CreateUserRequest)
        Cmd->>Cmd: current_user = get_current_user()
        Cmd->>Authz: is_satisfied_by(subject=current_user, target_role=role)
        alt not satisfied
            Authz-->>Cmd: raises AuthorizationError
            Cmd-->>Router: AuthorizationError
            Router-->>Client: 403 Forbidden
        else satisfied
            Cmd->>Svc: create_user_with_raw_password(...)
            Svc-->>Cmd: new User entity (+ UserRegisteredEvent recorded)
            Cmd->>Storage: add(user)
            Cmd->>Events: stage(events)
            Cmd->>Flush: flush()
            alt unique constraint violated
                Flush-->>Cmd: raises *AlreadyExistsError
                Cmd-->>Router: propagates
                Router-->>Client: 409 Conflict
            else flush ok
                Cmd->>Tx: commit()
                Cmd->>Events: dispatch(events)
                Cmd-->>Router: CreateUserResponse {id, created_at}
                Router-->>Client: 201 Created
            end
        end
    ```

    > The router (`make_create_user_router`) is a thin `dishka`-injected adapter: it parses `CreateUserRequest` from the JSON (JavaScript Object Notation) body via FastAPI, hands it to the injected `CreateUser` interactor — an **interactor**, i.e. a use-case class: one `execute()` method implementing a single application action — and returns whatever the interactor returns. All of the actual logic — authorization, uniqueness handling, event staging, commit ordering — lives in `CreateUser.execute()`, in `core`, with zero HTTP (HyperText Transfer Protocol)-specific code.

## Who can create whom

`CreateUser` authorizes against the **requested role**, not against the target user (there is no target user yet). It calls `authorize(CanManageRole(), context=RoleManagementContext(subject=current_user, target_role=role))`, where `CanManageRole.is_satisfied_by()` checks `role_hierarchy.get(subject.role, set())` against `target_role` — using the same shared `ROLE_HIERARCHY` mapping consumed by every other role-sensitive use case in this section:

!!! figure "ROLE_HIERARCHY — who can be granted which role"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        super_admin["SUPER_ADMIN"] --> admin["ADMIN"]
        super_admin --> user["USER"]
        admin --> user2["USER"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `ROLE_HIERARCHY` maps `SUPER_ADMIN → {ADMIN, USER}` and `ADMIN → {USER}` (`USER` maps to an empty set — a plain user can manage no one). So a caller with role `admin` requesting `role=admin` for the new account fails `CanManageRole` (`ADMIN`'s allowed set is only `{USER}`), while a `super_admin` caller can create either. This is exactly the "only super admins can create new admins" rule from the docstring, expressed as one shared table rather than an `if`/`else` special-cased to this one command.

Note there is no separate "does this user already exist" authorization check on the target here (unlike [Activate User](users-activate-user.md) or [Grant Admin](users-grant-admin.md), which additionally run `CanManageSubordinate` against an existing target user) — `CreateUser` only ever checks the *role being requested*, since the target account doesn't exist until this command creates it.

## Uniqueness is enforced at flush, not pre-checked

`CreateUser.execute()` does not query the database first to see if the username/email/phone number is already taken. It builds the `User` entity (an **Entity** — a Domain-Driven Design object with identity that persists over time, per [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are)), stages it via `UserTxStorage.add()`, and calls `Flusher.flush()` inside a `try`/`except` that re-raises `UsernameAlreadyExistsError`, `EmailAlreadyExistsError`, and `PhoneNumberAlreadyExistsError`. Those three exceptions are raised by [`SqlaFlusher`](../../../../src/app/outbound/adapters/sqla_flusher.py), which catches the real Postgres unique-constraint violation from `session.flush()` and translates it by constraint name (`UQ_USERS_USERNAME`, `UQ_USERS_EMAIL`, `UQ_USERS_PHONE_NUMBER`) into the matching domain exception. The router's `error_map` then turns each into `409 Conflict`. This closes the race-condition window a separate SELECT-then-INSERT pre-check would leave open between two concurrent signups.

## Domain events: stage before commit, dispatch after

`UserService.create_user_with_raw_password()` records a `UserRegisteredEvent` — a **Domain Event**, i.e. something that happened, per [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are) — on the new entity. `CreateUser.execute()` collects it via `user.collect_events()` and calls `EventDispatcher.stage(events)` **before** `flush()`/`commit()`, then `EventDispatcher.dispatch(events)` **after** `commit()` — the two-phase contract documented directly on the `EventDispatcher` port itself (`stage()`: "Call BEFORE the caller's own flush()/commit()."; `dispatch()`: "Call AFTER the caller's own commit()."). This ordering is what lets a background-dispatched handler be written to the transactional outbox in the *same* database transaction as the user row, closing the dual-write gap described in the Overview's capability table.

## Where to go next

- [Adding a New Use Case (Command)](adding-a-use-case.md) — the generic template this use case follows.
- [Users: Grant Admin](users-grant-admin.md) — the same `ROLE_HIERARCHY`/`CanManageRole` mechanism, applied to an *existing* user instead of at creation time.
- [Account: Sign Up](account-sign-up.md) — the public, unauthenticated counterpart to this admin-only endpoint.
