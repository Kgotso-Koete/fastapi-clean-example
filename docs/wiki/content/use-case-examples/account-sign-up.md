# Account: Sign Up

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/account/sign_up.py`](../../../../src/app/inbound/http/account/sign_up.py) — the route
    - [`src/app/outbound/auth_ctx/handlers/sign_up.py`](../../../../src/app/outbound/auth_ctx/handlers/sign_up.py) — the `SignUp` handler
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.create_user_with_raw_password`, where the password gets hashed and the domain event recorded
    - [`src/app/core/common/events/user_registered.py`](../../../../src/app/core/common/events/user_registered.py) — `UserRegisteredEvent`
    - [`src/app/core/common/events/handlers/send_welcome_email.py`](../../../../src/app/core/common/events/handlers/send_welcome_email.py) — the background subscriber to that event
    - [`src/app/outbound/auth_ctx/sqla_user_tx_storage.py`](../../../../src/app/outbound/auth_ctx/sqla_user_tx_storage.py) — `AuthSqlaUserTxStorage`
    - [`src/app/outbound/auth_ctx/exceptions.py`](../../../../src/app/outbound/auth_ctx/exceptions.py) — `AlreadyAuthenticatedError`
    - [`src/app/main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py) — `AuthProvider`, where `SignUp` and its collaborators are wired

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

`POST /account/signup/` is open to everyone, and is the origin point of the `UserRegisteredEvent` — the domain event that later triggers a welcome email in the background. It's a good first use case to trace because it touches nearly every mechanism this wiki documents elsewhere: value-object validation, a domain service, domain events (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what "value object" and "domain event" mean here), the transactional outbox, and (unlike `users/create_user`, its admin-only sibling covered on [Users: Create User](users-create-user.md)) no authorization check at all — anyone can call it.

## Request flow

!!! figure-wide "Sign-up: HTTP (HyperText Transfer Protocol) request through to the persisted user and staged event"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as make_sign_up_router
        participant Handler as SignUp\n(outbound/auth_ctx/handlers)
        participant CUS as CurrentUserService
        participant US as UserService
        participant Storage as AuthSqlaUserTxStorage
        participant ED as EventDispatcher\n(HybridEventDispatcher)
        participant DB as Postgres

        Client->>Router: POST /account/signup/ (SignUpRequest JSON)
        Router->>Handler: handler.execute(request)
        Handler->>CUS: get_current_user()
        CUS-->>Handler: raises AuthenticationError (no session)
        Note over Handler: caught -- "not logged in" is the\nexpected, allowed case for sign-up
        Handler->>Handler: validate into Username/RawPassword/\nEmail/PhoneNumber value objects
        Handler->>US: create_user_with_raw_password(...)
        US->>US: hash password (PasswordHasher port)
        US->>US: record UserRegisteredEvent on the new User
        US-->>Handler: User entity (with pending event)
        Handler->>Storage: add(user)
        Handler->>ED: stage(events)  -- before flush/commit
        Handler->>Storage: flush()  -- via Flusher port, raises *AlreadyExistsError on conflict
        Storage->>DB: INSERT user row (not yet committed)
        Handler->>DB: transaction_manager.commit()
        DB-->>Handler: committed
        Handler->>ED: dispatch(events)  -- after commit
        Handler-->>Router: UserQm
        Router-->>Client: 200 OK (UserQm JSON)
    ```

    > Read top to bottom: a logged-in caller is rejected before any validation happens; a fresh caller has their input parsed into value objects (which themselves throw `BusinessTypeError` subclasses on invalid input, mapped to `400` by the router); `UserService` does the actual password hashing and event recording; then `stage()` → `flush()` → `commit()` → `dispatch()` runs in that exact order, so the welcome-email event only ever fires for a signup that actually committed.

## Step 1 — The route

[`sign_up.py`](../../../../src/app/inbound/http/account/sign_up.py) follows the same shape as any other endpoint (see [Adding a New REST Endpoint](adding-a-rest-endpoint.md) for the generic version of this pattern):

```python
@router.post(
    "/signup/",
    error_map={
        StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        AuthorizationError: status.HTTP_403_FORBIDDEN,
        AlreadyAuthenticatedError: status.HTTP_403_FORBIDDEN,
        BusinessTypeError: status.HTTP_400_BAD_REQUEST,
        PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        UsernameAlreadyExistsError: status.HTTP_409_CONFLICT,
        EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
        PhoneNumberAlreadyExistsError: status.HTTP_409_CONFLICT,
    },
    status_code=status.HTTP_200_OK,
    description=getdoc(SignUp),
)
@inject
async def sign_up(request: SignUpRequest, handler: FromDishka[SignUp]) -> UserQm:
    return await handler.execute(request)
```

Notice there's no `dependencies=[Depends(APIKeyCookie(...))]` here, unlike `log_out`/`change_password` — signing up requires no existing session, by definition. It's registered without a cookie dependency in [`router.py`](../../../../src/app/inbound/http/account/router.py)'s `make_account_router`.

## Step 2 — The handler

[`SignUp`](../../../../src/app/outbound/auth_ctx/handlers/sign_up.py) is not under `core/commands/` like `CreateUser` is — it lives under `outbound/auth_ctx/`, this codebase's self-contained authentication context (see the docstring on [`AuthSession`](../../../../src/app/outbound/auth_ctx/model.py) for why: it's deliberately structured so it *could* graduate into its own [bounded context](../architecture/outbound-layer.md) later — a Domain-Driven Design term for an explicit boundary within which one domain model applies consistently — without disturbing `core`). Its first move is a "reject if already authenticated" check, done by deliberately trying to resolve a current user and expecting failure:

```python
try:
    await self._current_user_service.get_current_user()
    raise AlreadyAuthenticatedError
except AuthenticationError:
    pass
```

From there it mirrors `CreateUser`'s body almost exactly: parse into value objects, call `UserService.create_user_with_raw_password(...)`, add the entity to storage, `stage()` its events, `flush()`, `commit()`, `dispatch()`. The one real difference from `CreateUser`: no `authorize()` call, no `role` parameter — every sign-up gets `UserRole.USER` (`UserService.create_user`'s default), never an admin role. `AuthSqlaUserTxStorage` — a small, auth-context-local storage adapter distinct from `SqlaUserTxStorage` used elsewhere — is what `add()` goes to; see [Core Patterns → Ports and Adapters](../core-patterns/ports-and-adapters.md) for why this deliberate duplication (rather than a shared class) is the pattern this codebase prefers.

## Password hashing and the domain event

Both happen inside [`UserService.create_user_with_raw_password`](../../../../src/app/core/common/services/user.py), not in `SignUp` itself:

```python
async def create_user_with_raw_password(self, user_id, username, email, phone_number, raw_password, *, now, role=UserRole.USER, is_active=True) -> User:
    password_hash = await self._password_hasher.hash(raw_password)
    return self.create_user(user_id, username, email, phone_number, password_hash, now=now, role=role, is_active=is_active)
```

[`create_user`](../../../../src/app/core/common/services/user.py) (the synchronous half) constructs the `User` entity and immediately records the event on it:

```python
user.record_event(
    UserRegisteredEvent(occurred_at=now.value, user_id=user_id, username=username.value, email=email.value)
)
```

`UserRegisteredEvent` just carries the data a subscriber needs — nothing about *how* it will be handled. That's decided per-handler: [`SendWelcomeEmail`](../../../../src/app/core/common/events/handlers/send_welcome_email.py) declares `DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "background"`, so `HybridEventDispatcher` writes it to the transactional outbox at `stage()` time instead of running it inline — the signup response returns before any email is sent. See [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) for the full mechanism, and [Users: Create User](users-create-user.md) for the same event fired from the admin-only path.

## Where to go next

- [Account: Log In](account-log-in.md) — what a freshly-signed-up user does next.
- [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) — the `stage()`/`dispatch()`/outbox mechanism this page relies on.
- [Users: Create User](users-create-user.md) — the admin-only sibling of this same underlying `UserService` call.
