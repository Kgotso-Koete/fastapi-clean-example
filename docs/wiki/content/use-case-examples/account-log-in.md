# Account: Log In

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/account/log_in.py`](../../../../src/app/inbound/http/account/log_in.py) — the route
    - [`src/app/outbound/auth_ctx/handlers/log_in.py`](../../../../src/app/outbound/auth_ctx/handlers/log_in.py) — the `LogIn` handler
    - [`src/app/outbound/auth_ctx/service.py`](../../../../src/app/outbound/auth_ctx/service.py) — `AuthService.issue_session`
    - [`src/app/outbound/auth_ctx/jwt_processor.py`](../../../../src/app/outbound/auth_ctx/jwt_processor.py) — `JwtProcessor.encode`
    - [`src/app/outbound/auth_ctx/cookie_manager.py`](../../../../src/app/outbound/auth_ctx/cookie_manager.py) — `CookieManager.stage_set`
    - [`src/app/inbound/http/auth_cookie_middleware.py`](../../../../src/app/inbound/http/auth_cookie_middleware.py) — `AuthCookieMiddleware`, where the staged cookie actually gets attached to the HTTP response
    - [`src/app/outbound/auth_ctx/model.py`](../../../../src/app/outbound/auth_ctx/model.py) — `AuthSession`
    - [`src/app/outbound/auth_ctx/sqla_user_tx_storage.py`](../../../../src/app/outbound/auth_ctx/sqla_user_tx_storage.py) — `AuthSqlaUserTxStorage.get_by_username`

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

`POST /account/login/` authenticates a username/password pair and, on success, starts a server-side session — not a stateless bearer JWT (JSON Web Token). The JWT this codebase issues holds only a session ID; the session itself (its expiration, whether it's been revoked) lives in Postgres, so a session can be killed server-side at any time (see [Account: Log Out](account-log-out.md)). That distinction is the main thing worth tracing carefully here.

## Request flow

!!! figure-wide "Log-in: credential check through to the session cookie"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as make_log_in_router
        participant Handler as LogIn
        participant CUS as CurrentUserService
        participant Storage as AuthSqlaUserTxStorage
        participant US as UserService
        participant Auth as AuthService
        participant JWT as JwtProcessor
        participant Cookie as CookieManager
        participant MW as AuthCookieMiddleware
        participant DB as Postgres

        Client->>Router: POST /account/login/ (LogInRequest JSON)
        Router->>Handler: handler.execute(request)
        Handler->>CUS: get_current_user()
        CUS-->>Handler: raises AuthenticationError (no session yet)
        Note over Handler: caught -- proceed as a fresh login attempt
        Handler->>Storage: get_by_username(username)
        Storage-->>Handler: User or None
        Handler->>US: is_password_valid(user, password)
        US-->>Handler: True / False
        alt invalid credentials or inactive account
            Handler-->>Router: raise AuthenticationError
            Router-->>Client: 401 Unauthorized
        else valid, active user
            Handler->>Auth: issue_session(user.id_)
            Auth->>DB: INSERT AuthSession row + commit
            Auth->>JWT: encode(session)
            JWT-->>Auth: signed JWT (carries session id, "sid")
            Auth->>Cookie: stage_set(token)
            Cookie->>Cookie: request.state.staged_cookie = token
            Handler-->>Router: UserQm
            Router-->>Client: 200 OK (UserQm JSON)
            MW->>MW: after response built, reads request.state.staged_cookie
            MW-->>Client: Set-Cookie: <cookie_name>=<jwt> (HttpOnly)
        end
    ```

    > The cookie is not set directly by the handler or the router — it's **staged** onto `request.state` during `execute()`, and only actually attached to the outgoing response afterward, by [`AuthCookieMiddleware`](../../../../src/app/inbound/http/auth_cookie_middleware.py) wrapping the whole app. This indirection is what lets `AuthService` (deep in `outbound`) affect the HTTP (HyperText Transfer Protocol) response without importing anything from Starlette's response API (Application Programming Interface) itself.

## Step 1 — The route

[`log_in.py`](../../../../src/app/inbound/http/account/log_in.py) is a standard thin route, mapping `AuthenticationError` to `401` and `AlreadyAuthenticatedError` to `403` alongside the usual `error_map` entries — see [Adding a New REST Endpoint](adding-a-rest-endpoint.md) for the generic pattern:

```python
@router.post("/login/", error_map={..., AuthenticationError: status.HTTP_401_UNAUTHORIZED, ...}, status_code=status.HTTP_200_OK, description=getdoc(LogIn))
@inject
async def log_in(request: LogInRequest, handler: FromDishka[LogIn]) -> UserQm:
    return await handler.execute(request)
```

## Step 2 — The handler: credential verification

[`LogIn.execute`](../../../../src/app/outbound/auth_ctx/handlers/log_in.py) rejects an already-authenticated caller the same way `SignUp` does, then looks the user up by username, checks the password, and checks the account is active — each failure path raising a distinct error so the router's `error_map` can turn it into the right status code:

```python
user = await self._user_tx_storage.get_by_username(username)
if user is None:
    raise AuthenticationError

if not await self._user_service.is_password_valid(user, password):
    raise AuthenticationError

if not user.is_active:
    raise AuthenticationError(AUTH_ACCOUNT_INACTIVE)

await self._auth_service.issue_session(user.id_)
```

`is_password_valid` delegates to the `PasswordHasher` port's `verify()` — the same hashing scheme (bcrypt with a server-side pepper, per [`main/ioc/core.py`](../../../../src/app/main/ioc/core.py)'s `provide_password_hasher`) used to create the hash at sign-up time.

## Step 3 — Issuing the session

[`AuthService.issue_session`](../../../../src/app/outbound/auth_ctx/service.py) is where the actual session record, JWT, and staged cookie all get created, in this order:

```python
async def issue_session(self, user_id: UserId) -> None:
    session = AuthSession(id_=create_session_id(), user_id=user_id, expiration=self._session_timer.expiration_from_now)
    self._session_tx_storage.add(session)
    await self._transaction_manager.commit()
    token = self._jwt_processor.encode(session)
    self._cookie_manager.stage_set(token)
```

The session row is committed to Postgres *before* the JWT is even created — the JWT only ever encodes a `sid` claim (the session's ID) and an `exp` claim, per [`JwtProcessor.encode`](../../../../src/app/outbound/auth_ctx/jwt_processor.py):

```python
payload = {self.SESSION_ID_CLAIM: auth_session.id_, self.EXPIRATION_CLAIM: auth_session.expiration.value.timestamp()}
return jwt.encode(payload, key=self._secret, algorithm=self._algorithm)
```

No username, role, or other user data is ever embedded in the token itself — every subsequent request re-resolves the current user from the database via the session ID, so revoking a session (deleting its row) invalidates the JWT immediately, without needing a token blocklist. This is what [`CurrentUserService`](../../../../src/app/core/common/authorization/current_user_service.py) does on every authenticated request: `IdentityProvider.get_current_user_id()` → `AuthSessionIdentityProvider` → `AuthService.get_current_user_id()`, which decodes the cookie, looks the session up, and checks `is_expired`/`needs_refresh` — silently re-issuing a refreshed cookie if the session is getting close to expiry.

## Step 4 — The cookie actually reaching the client

[`CookieManager.stage_set`](../../../../src/app/outbound/auth_ctx/cookie_manager.py) doesn't touch the HTTP response at all — it just records the token on the request:

```python
def stage_set(self, value: str) -> None:
    setattr(self._request.state, STAGED_COOKIE, value)
```

[`AuthCookieMiddleware.dispatch`](../../../../src/app/inbound/http/auth_cookie_middleware.py), wrapping every request, reads that same `request.state` attribute *after* the route has already produced its response, and only then calls `response.set_cookie(...)` with the configured `httponly`/`secure`/`samesite` flags:

```python
staged = getattr(request.state, STAGED_COOKIE, self.MISSING)
if staged is self.MISSING:
    return response
value = cast(str | None, staged)
if value is None:
    response.delete_cookie(key=self._cookie_name, path=self._cookie_path)
    return response
response.set_cookie(key=self._cookie_name, value=value, path=self._cookie_path, httponly=self._cookie_httponly, secure=self._cookie_secure, samesite=self._cookie_samesite)
```

This same staging mechanism is reused, with a `None` value instead, to *delete* the cookie on logout — see [Account: Log Out](account-log-out.md).

## Where to go next

- [Account: Sign Up](account-sign-up.md) — how the account being logged into was created.
- [Account: Log Out](account-log-out.md) — how a session issued here gets revoked.
- [Core Patterns → Ports and Adapters](../core-patterns/ports-and-adapters.md) — the `IdentityProvider`/`AccessRevoker` ports `CurrentUserService` depends on.
