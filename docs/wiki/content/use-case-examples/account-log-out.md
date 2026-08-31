# Account: Log Out

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/account/log_out.py`](../../../../src/app/inbound/http/account/log_out.py) — the route
    - [`src/app/outbound/auth_ctx/handlers/log_out.py`](../../../../src/app/outbound/auth_ctx/handlers/log_out.py) — the `LogOut` handler
    - [`src/app/outbound/auth_ctx/service.py`](../../../../src/app/outbound/auth_ctx/service.py) — `AuthService.logout_current_session`
    - [`src/app/outbound/auth_ctx/cookie_manager.py`](../../../../src/app/outbound/auth_ctx/cookie_manager.py) — `CookieManager.stage_delete`
    - [`src/app/inbound/http/auth_cookie_middleware.py`](../../../../src/app/inbound/http/auth_cookie_middleware.py) — where the staged deletion actually removes the cookie
    - [`src/app/core/common/authorization/current_user_service.py`](../../../../src/app/core/common/authorization/current_user_service.py) — `CurrentUserService.get_current_user`, the auth gate this endpoint sits behind

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

`DELETE /account/logout/` is the simplest use case in this codebase's account/user set — deliberately so, since it demonstrates the minimum needed to actually revoke a session, rather than merely forgetting it client-side. Logging out here means two separate things happen: the session row is deleted from Postgres, and the client's cookie is cleared — losing either half would leave a real security gap (a stolen cookie that still works, or a browser that "logged out" but whose session the server would still honor if replayed).

## Request flow

!!! figure-wide "Log-out: session revocation and cookie clearing"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as make_log_out_router
        participant Handler as LogOut
        participant CUS as CurrentUserService
        participant Auth as AuthService
        participant Cookie as CookieManager
        participant MW as AuthCookieMiddleware
        participant DB as Postgres

        Client->>Router: DELETE /account/logout/ (cookie attached)
        Router->>Handler: handler.execute()
        Handler->>CUS: get_current_user()
        alt no valid session
            CUS-->>Handler: raises AuthorizationError / AuthenticationError
            Router-->>Client: 401 / 403
        else valid session
            CUS-->>Handler: current User
            Handler->>Auth: logout_current_session()
            Auth->>Cookie: stage_delete()
            Cookie->>Cookie: request.state.staged_cookie = None
            Auth->>DB: DELETE session row + commit
            Handler-->>Router: None
            Router-->>Client: 204 No Content
            MW->>MW: reads request.state.staged_cookie (None)
            MW-->>Client: Set-Cookie deleted (response.delete_cookie)
        end
    ```

    > Note that `stage_delete()` runs *before* the database delete + commit, not after — see the "why order matters" note below.

## Step 1 — The route

[`log_out.py`](../../../../src/app/inbound/http/account/log_out.py) is guarded by the same cookie-auth `Depends(APIKeyCookie(...))` every protected endpoint uses, and returns `204 No Content` — there's nothing meaningful to return once the session is gone:

```python
@router.delete(
    "/logout/",
    error_map={
        AuthenticationError: status.HTTP_401_UNAUTHORIZED,
        StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        AuthorizationError: status.HTTP_403_FORBIDDEN,
    },
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(APIKeyCookie(name=cookie_name))],
    description=getdoc(LogOut),
)
@inject
async def log_out(handler: FromDishka[LogOut]) -> None:
    await handler.execute()
```

The `Depends(APIKeyCookie(...))` here doesn't actually do the authentication itself — it's what makes Swagger UI show a cookie-auth padlock on this endpoint. The real authentication check is `CurrentUserService.get_current_user()`, called explicitly inside the handler.

## Step 2 — The handler

[`LogOut.execute`](../../../../src/app/outbound/auth_ctx/handlers/log_out.py) is two lines:

```python
async def execute(self) -> None:
    await self._current_user_service.get_current_user()
    await self._auth_service.logout_current_session()
```

Calling `get_current_user()` and discarding the result looks redundant, but it's doing real work: it's what actually verifies there's a valid, active session to log out of in the first place — a caller with an expired or already-terminated session gets a `401`/`403` here rather than a false "success".

## Step 3 — Revoking the session

[`AuthService.logout_current_session`](../../../../src/app/outbound/auth_ctx/service.py):

```python
async def logout_current_session(self) -> None:
    self._cookie_manager.stage_delete()
    session_id = self._get_session_id()
    if session_id is not None:
        await self._session_tx_storage.delete(session_id)
        await self._transaction_manager.commit()
```

Deleting the session row is what makes the revocation real and immediate: because the JWT (JSON Web Token) itself carries no user data (see [Account: Log In](account-log-in.md)) and every request re-checks the session against the database, deleting this one row is sufficient — no separate token-blocklist mechanism is needed. `stage_delete()` runs unconditionally, first, so even a caller whose cookie doesn't decode to a valid session ID still gets their cookie cleared client-side.

## Step 4 — Clearing the cookie

[`CookieManager.stage_delete`](../../../../src/app/outbound/auth_ctx/cookie_manager.py) stages a `None` value, reusing the exact same `request.state` slot `stage_set` uses on login:

```python
def stage_delete(self) -> None:
    setattr(self._request.state, STAGED_COOKIE, None)
```

[`AuthCookieMiddleware`](../../../../src/app/inbound/http/auth_cookie_middleware.py) treats a staged `None` as "delete", not "do nothing" — it calls `response.delete_cookie(...)` rather than `response.set_cookie(...)`:

```python
value = cast(str | None, staged)
if value is None:
    response.delete_cookie(key=self._cookie_name, path=self._cookie_path)
    return response
```

This is why `stage_set`/`stage_delete` share one mechanism instead of being two unrelated code paths: the middleware only ever needs to ask "is anything staged, and if so, is it a real token or `None`?" — it doesn't need to know which use case (login vs. logout vs. session refresh) triggered the staging.

## Where to go next

- [Account: Log In](account-log-in.md) — how the session being revoked here was created, and the same cookie-staging mechanism used in reverse.
- [Account: Change Password](account-change-password.md) — another use case that revokes sessions, but *all* of a user's sessions at once, not just the current one.
