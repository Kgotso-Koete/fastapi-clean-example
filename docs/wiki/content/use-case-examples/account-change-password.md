# Account: Change Password

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/account/change_password.py`](../../../../src/app/inbound/http/account/change_password.py) — the route
    - [`src/app/outbound/auth_ctx/handlers/change_password.py`](../../../../src/app/outbound/auth_ctx/handlers/change_password.py) — the `ChangePassword` handler
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.is_password_valid` / `change_password`
    - [`src/app/outbound/auth_ctx/service.py`](../../../../src/app/outbound/auth_ctx/service.py) — `AuthService.logout_current_session` / `revoke_all_sessions`
    - [`src/app/core/common/authorization/current_user_service.py`](../../../../src/app/core/common/authorization/current_user_service.py) — `get_current_user(for_update=True)`
    - [`src/app/outbound/auth_ctx/exceptions.py`](../../../../src/app/outbound/auth_ctx/exceptions.py) — `AuthenticationChangeError`, `ReAuthenticationError`

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

`PUT /account/password/` lets an authenticated user change their own password, given their current one. Structurally it's the most defensive use case in this set: it re-verifies the caller's identity with their password (not just their session cookie), locks the user row for the duration of the change, and — as a deliberate security measure — logs out every session that user has, including the one making this very request, forcing a fresh login with the new password afterward.

## Request flow

!!! figure-wide "Change password: re-authentication through to full session revocation"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as make_change_password_router
        participant Handler as ChangePassword
        participant CUS as CurrentUserService
        participant US as UserService
        participant Auth as AuthService
        participant DB as Postgres

        Client->>Router: PUT /account/password/ (current + new password)
        Router->>Handler: handler.execute(request)
        Handler->>CUS: get_current_user(for_update=True)
        CUS->>DB: SELECT ... FOR UPDATE
        DB-->>CUS: locked User row
        CUS-->>Handler: current User

        Handler->>Handler: current_password == new_password?
        alt same password
            Handler-->>Router: raise AuthenticationChangeError
            Router-->>Client: 400 Bad Request
        end

        Handler->>US: is_password_valid(user, current_password)
        alt current password wrong
            US-->>Handler: False
            Handler-->>Router: raise ReAuthenticationError
            Router-->>Client: 403 Forbidden
        else current password correct
            US-->>Handler: True
            Handler->>US: change_password(user, new_password, now)
            US->>US: hash new password, set updated_at
            Handler->>DB: transaction_manager.commit()
            Handler->>Auth: logout_current_session()
            Auth->>DB: DELETE this session + commit; clear cookie
            Handler->>Auth: revoke_all_sessions(user.id_)
            Auth->>DB: DELETE every session row for this user + commit
            Handler-->>Router: None
            Router-->>Client: 204 No Content (no valid cookie remains)
        end
    ```

    > The row lock (`for_update=True`), the password-hash update, and both rounds of session revocation are what make this endpoint safe to expose without any additional confirmation step — even if an attacker had an active session on the account, changing the password ends it immediately, in the same request.

## Step 1 — The route

[`change_password.py`](../../../../src/app/inbound/http/account/change_password.py) is the one route in this set with its own Pydantic request schema, purely for a nicer Swagger UI, immediately converted into the handler's own plain dataclass request:

```python
class ChangePasswordRequestSchema(BaseModel):
    """Using Pydantic model here is generally unnecessary. It's only implemented to render specific Swagger UI."""
    model_config = ConfigDict(frozen=True)
    current_password: str
    new_password: str

@router.put(
    "/password/",
    error_map={
        AuthenticationError: status.HTTP_401_UNAUTHORIZED,
        AuthenticationChangeError: status.HTTP_400_BAD_REQUEST,
        ReAuthenticationError: status.HTTP_403_FORBIDDEN,
        ...
    },
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(APIKeyCookie(name=cookie_name))],
    description=getdoc(ChangePassword),
)
@inject
async def change_password(request_schema: ChangePasswordRequestSchema, handler: FromDishka[ChangePassword]) -> None:
    request = ChangePasswordRequest(current_password=request_schema.current_password, new_password=request_schema.new_password)
    await handler.execute(request)
```

`ChangePasswordRequest` (the handler's own dataclass, distinct from the Pydantic schema above it) is what keeps `core`/`outbound` from depending on Pydantic at all — the router does the one-line translation at the boundary, same pattern used throughout `inbound`.

## Step 2 — Locking the current user

[`ChangePassword.execute`](../../../../src/app/outbound/auth_ctx/handlers/change_password.py) starts by fetching the current user *with a row lock*:

```python
current_user = await self._current_user_service.get_current_user(for_update=True)
```

[`CurrentUserService.get_current_user`](../../../../src/app/core/common/authorization/current_user_service.py) passes `for_update` straight through to the storage port's `get_by_id(..., for_update=True)`, which issues `SELECT ... FOR UPDATE` — this holds a row-level lock on the user for the rest of the transaction, so a concurrent second change-password (or admin action on the same user) can't interleave with this one and leave the account in an inconsistent state.

## Step 3 — Two checks before anything changes

[`ChangePassword.execute`](../../../../src/app/outbound/auth_ctx/handlers/change_password.py) continues with two cheap checks before touching the database:

```python
current_password = RawPassword(request.current_password)
new_password = RawPassword(request.new_password)
if current_password == new_password:
    raise AuthenticationChangeError

if not await self._user_service.is_password_valid(current_user, current_password):
    raise ReAuthenticationError
```

`RawPassword` is a value object (a small, immutable type defined purely by its value — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)), so `current_password == new_password` is a plain-text comparison caught *before* anything is hashed or touches the database — a cheap, immediate rejection of a no-op request. `is_password_valid` (the same `UserService` method [Account: Log In](account-log-in.md) uses) is the actual re-authentication step: proof the caller really knows the account's current password, not just that they hold a valid session cookie.

## Step 4 — Changing the password, then revoking everything

[`ChangePassword.execute`](../../../../src/app/outbound/auth_ctx/handlers/change_password.py) then commits the new password and revokes every session:

```python
await self._user_service.change_password(current_user, new_password, now=self._utc_timer.now)
await self._transaction_manager.commit()

# Security: Invalidate the current cookie and wipe all sessions from the database
await self._auth_service.logout_current_session()
await self._auth_service.revoke_all_sessions(current_user.id_)
```

[`UserService.change_password`](../../../../src/app/core/common/services/user.py) just re-hashes and re-assigns `password_hash`/`updated_at` on the entity (the `User` object — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what "entity" means here) — the same `PasswordHasher` port used at signup. Once that's committed, the handler calls both revocation methods on [`AuthService`](../../../../src/app/outbound/auth_ctx/service.py): `logout_current_session()` (the same one-session deletion [Account: Log Out](account-log-out.md) covers, which also clears this response's cookie) followed by `revoke_all_sessions(current_user.id_)`, which deletes *every* session row for that user — including ones from other devices/browsers, which get silently logged out the next time they try to use their now-invalid cookie.

## Where to go next

- [Account: Log In](account-log-in.md) — how a session is issued again after this endpoint revokes them all.
- [Account: Log Out](account-log-out.md) — the single-session revocation this endpoint reuses, then extends to every session.
- [Core Patterns → Ports and Adapters](../core-patterns/ports-and-adapters.md) — the `PasswordHasher` port both this and sign-up depend on.
