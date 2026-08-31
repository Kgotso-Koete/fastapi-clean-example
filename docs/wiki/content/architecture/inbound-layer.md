# Inbound Layer (HTTP / Presentation)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/root_router.py`](../../../../src/app/inbound/http/root_router.py) — the top-level FastAPI router
    - [`src/app/inbound/http/api_v1_router.py`](../../../../src/app/inbound/http/api_v1_router.py) — mounts `/api/v1`
    - [`src/app/inbound/http/account/`](../../../../src/app/inbound/http/account/) — signup/login/logout/change-password endpoints
    - [`src/app/inbound/http/users/`](../../../../src/app/inbound/http/users/) — admin user-management endpoints
    - [`src/app/inbound/http/errors/`](../../../../src/app/inbound/http/errors/) — the error-mapping router wrapper and the global exception middleware
    - [`src/app/inbound/http/health/`](../../../../src/app/inbound/http/health/) — liveness/readiness probes
    - [`src/app/inbound/http/debug/`](../../../../src/app/inbound/http/debug/) — a deliberately temporary error-testing endpoint
    - [`src/app/inbound/http/auth_cookie_middleware.py`](../../../../src/app/inbound/http/auth_cookie_middleware.py) — commits a staged cookie onto the response

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What lives here

`inbound` is how the outside world reaches this application: FastAPI routers, request/response models, and the middleware that turns whatever a use case raised into an HTTP (HyperText Transfer Protocol) response. Per [Layer Dependencies & Import Rules](layer-dependencies.md), it may import `outbound` and `core` freely but never `main`. Every route handler here is thin by design — it resolves a `core` or `auth_ctx` use case via Dishka injection, calls `execute()`, and returns whatever came back; none of the actual business logic lives in this layer.

## Router mounting

!!! figure "Router mounting: root → api_v1 → account / users"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        root["make_fastapi_root_router()"]

        subgraph rootmounts["mounted directly on root"]
            redirect["GET / → redirect to /docs"]
            health["health router (/livez/, /healthz/)"]
            debug["debug router (/debug/test-error)"]
        end

        subgraph v1["make_v1_router() — prefix /api/v1"]
            subgraph account["account router — prefix /account"]
                signup["POST /signup/"]
                login["POST /login/"]
                changepw["PUT /password/"]
                logout["DELETE /logout/"]
            end
            subgraph users["users router — prefix /users, cookie-secured"]
                createuser["POST /"]
                listusers["GET /"]
                setpw["PUT /{user_id}/password/"]
                grant["PUT /{user_id}/roles/admin/"]
                revoke["DELETE /{user_id}/roles/admin/"]
                activate["PUT /{user_id}/activation/"]
                deactivate["DELETE /{user_id}/activation/"]
            end
        end

        root --> rootmounts
        root --> v1

        linkStyle default stroke-width:3px,stroke:#333333
        style rootmounts stroke-width:1px,stroke:#333333
        style v1 stroke-width:1px,stroke:#333333
        style account stroke-width:1px,stroke:#333333
        style users stroke-width:1px,stroke:#333333
    ```

    > `make_fastapi_root_router()` (in [`root_router.py`](../../../../src/app/inbound/http/root_router.py)) mounts a bare `GET /` redirect to `/docs`, the health router, the debug router, and `make_v1_router()` (in [`api_v1_router.py`](../../../../src/app/inbound/http/api_v1_router.py)), which itself prefixes everything under it with `/api/v1` and mounts the `account` and `users` routers. `users` additionally carries a router-level `Depends(APIKeyCookie(name=cookie_name))` dependency — every route under `/api/v1/users` requires the session cookie to be present before any handler body runs, whereas `account`'s own routes (signup/login) are intentionally open. The debug router (`test_error.py`) is explicitly documented as temporary — its own docstring says "Remove this file after testing alerting functionality."

## Anatomy of one route: error mapping

Every route in `account/` and `users/` is built with `make_error_aware_router()` (from [`errors/router.py`](../../../../src/app/inbound/http/errors/router.py)), a thin wrapper around the third-party `fastapi-error-map` package's `ErrorAwareRouter`. Each endpoint declares an explicit `error_map` translating a `core`/`outbound` exception type straight to an HTTP status code — e.g. [`account/sign_up.py`](../../../../src/app/inbound/http/account/sign_up.py):

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

This keeps every knowledge of "what HTTP status a given business failure deserves" in `inbound`, where it belongs — `core`/`outbound` exceptions (`BusinessTypeError`, `AuthorizationError`, `StorageError`, …) carry no HTTP concept at all. Anything raised that *isn't* in the map falls through to the global exception middleware below.

## Error-handling middleware chain

!!! figure "Middleware order and where an exception is actually caught"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        request(["incoming request"])
        gem["GlobalExceptionMiddleware\n(pure ASGI)"]
        acm["AuthCookieMiddleware\n(BaseHTTPMiddleware)"]
        router["ErrorAwareRouter\n(per-route error_map)"]
        handler["route handler → core/auth_ctx use case"]

        request --> gem --> acm --> router --> handler
        handler -.->|mapped exception| router
        handler -.->|unmapped exception| gem

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `GlobalExceptionMiddleware` ([`errors/exception_middleware.py`](../../../../src/app/inbound/http/errors/exception_middleware.py)) is registered **above** `AuthCookieMiddleware` ([`auth_cookie_middleware.py`](../../../../src/app/inbound/http/auth_cookie_middleware.py)) in the stack, and is a plain ASGI (Asynchronous Server Gateway Interface) middleware rather than a `BaseHTTPMiddleware` subclass. Its own docstring explains why: `BaseHTTPMiddleware`'s `call_next` re-raises an exception even after Starlette's router-level `ExceptionMiddleware` already handled it, producing a duplicate traceback once it reaches uvicorn. Sitting above `AuthCookieMiddleware` as pure ASGI catches an unmapped exception before that duplication can happen. When it does catch one, it logs it, increments the `app_unhandled_exceptions_total` Prometheus counter (labeled by exception type), best-effort resolves the current user for the log/alert context, and — if `AlertSettings.ENABLED` and the per-exception-type cooldown allows it — sends an email alert. A mapped exception, by contrast, never reaches this middleware at all: `ErrorAwareRouter` translates it to the mapped status code directly at the route level.

`AuthCookieMiddleware` itself is unrelated to error handling — it's what commits a session cookie onto the outgoing response after a use case (e.g. `LogIn`) calls `CookieManager.stage_set()`/`stage_delete()` on `request.state`, since a use case in `outbound.auth_ctx` has no direct access to the FastAPI `Response` object being built.

## Health checks

[`health/router.py`](../../../../src/app/inbound/http/health/router.py) exposes `/livez/` (always `"OK"`, no dependencies) and `/healthz/` (injects an `AsyncSession` and runs `db_check`, from [`health/checks.py`](../../../../src/app/inbound/http/health/checks.py), which executes `SELECT 1`). As covered in [Layer Dependencies & Import Rules](layer-dependencies.md#what-the-linter-does-not-catch), this is the concrete example of `inbound` reaching directly for a third-party type (`sqlalchemy.ext.asyncio.AsyncSession`) instead of going through a `core` port — the import-linter contracts don't flag it, since they only police imports between `app.main`/`app.inbound`/`app.outbound`/`app.core`, not which third-party libraries any one of them reaches for.

## Where to go next

- [Layer Dependencies & Import Rules](layer-dependencies.md) — the enforced rule that `inbound` may depend on `outbound`/`core` but never `main`.
- [Outbound Layer (Infrastructure Adapters)](outbound-layer.md) — the `auth_ctx` handlers (`SignUp`, `LogIn`, …) every `account/` route resolves via Dishka.
- [Main (Composition Root)](main-composition-root.md) — where `setup_middlewares()` actually registers the middleware chain shown above.
