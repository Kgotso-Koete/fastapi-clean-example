# Error Handling (error_map Pattern)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/errors/router.py`](../../../../src/app/inbound/http/errors/router.py) — `make_error_aware_router()`, the factory every router in this codebase is built from
    - [`src/app/inbound/http/errors/rules.py`](../../../../src/app/inbound/http/errors/rules.py) — shared `Rule` constants, e.g. `HTTP_503_SERVICE_UNAVAILABLE_RULE`
    - [`src/app/inbound/http/errors/callbacks.py`](../../../../src/app/inbound/http/errors/callbacks.py) — `log_info`, an `on_error` callback
    - [`src/app/inbound/http/errors/exception_middleware.py`](../../../../src/app/inbound/http/errors/exception_middleware.py) — `GlobalExceptionMiddleware`, the catch-all for everything `error_map` doesn't cover
    - [`src/app/inbound/http/errors/internal_server_error.py`](../../../../src/app/inbound/http/errors/internal_server_error.py) — the JSON body `GlobalExceptionMiddleware` returns for a genuine 500
    - [`src/app/inbound/http/errors/openapi_responses.py`](../../../../src/app/inbound/http/errors/openapi_responses.py) — `SERVER_ERROR_RESPONSES`, the app-wide OpenAPI 500 entry
    - [`src/app/inbound/http/errors/alerting.py`](../../../../src/app/inbound/http/errors/alerting.py) — `AlertCooldown`, used by `GlobalExceptionMiddleware` (full depth on [Observability](../infrastructure-services/observability.md))
    - [`src/app/inbound/http/api_v1_router.py`](../../../../src/app/inbound/http/api_v1_router.py) — where `SERVER_ERROR_RESPONSES` is applied, once, for the whole `/api/v1` tree
    - [`src/app/inbound/http/users/create_user.py`](../../../../src/app/inbound/http/users/create_user.py) and [`src/app/inbound/http/account/sign_up.py`](../../../../src/app/inbound/http/account/sign_up.py) — two real `error_map={...}` declarations
    - Third-party: [`fastapi-error-map`](https://pypi.org/project/fastapi-error-map/) (installed as `fastapi_error_map`) — the library this whole page documents the usage of

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The idea in one sentence

Every route in this codebase declares, right on its `@router.post(...)`/`@router.get(...)` decorator, exactly which exception types it expects and which HTTP (HyperText Transfer Protocol) status each one becomes — an `error_map={ExceptionType: status_code, ...}` dict — so that translating a business exception into a response is a declaration next to the route, not a hidden `try`/`except` buried in a use case or a generic `@app.exception_handler(Exception)` far away from the code that actually raises it. Anything a route's `error_map` does *not* list is a genuinely unexpected failure, and falls through to a completely separate, app-wide safety net: `GlobalExceptionMiddleware`, covered in depth on [Observability (Prometheus, Grafana, Loki)](../infrastructure-services/observability.md).

## Two tiers, not one

!!! figure "Two tiers of error handling"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph tier1["Tier 1 -- per route, declared"]
            known["Exception type IS listed<br/>in THIS route's error_map"]
            resolve1["ErrorAwareRoute catches it,<br/>resolves the matching Rule"]
            out1["structured() envelope<br/>+ the mapped 4xx/5xx status"]
        end
        subgraph tier2["Tier 2 -- app-wide, catch-all"]
            unknown["Exception type NOT covered<br/>by the route's error_map"]
            reraise["ErrorAwareRoute re-raises it,<br/>GlobalExceptionMiddleware catches it"]
            alert["log + Prometheus counter +<br/>AlertCooldown-gated email"]
            out2["structured() envelope<br/>(opaque body) + 500"]
        end

        known --> resolve1 --> out1
        unknown --> reraise --> alert --> out2

        linkStyle default stroke-width:3px,stroke:#333333
        style tier1 stroke-width:1px,stroke:#333333
        style tier2 stroke-width:1px,stroke:#333333
    ```

    > This page is about Tier 1 — the per-route, declarative `error_map`. Tier 2 is [`GlobalExceptionMiddleware`](../../../../src/app/inbound/http/errors/exception_middleware.py), which already has its own page ([Observability](../infrastructure-services/observability.md)); it's mentioned here only to draw the boundary precisely: `error_map` handles the exception types a route's author already knows can happen (a duplicate username, a down database, a missing session) and has deliberately chosen an HTTP status for. `GlobalExceptionMiddleware` handles everything else — by definition, the exceptions nobody wrote a rule for, which is exactly why those are the ones worth an on-call email rather than just an HTTP status.

## A concrete request, both ways

!!! figure "One mapped exception, one unmapped exception"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        start(["Route's own logic raises"]) --> check{"Does err's type, or an<br/>ancestor, appear in<br/>this route's error_map?"}

        check -->|"yes -- e.g. AuthenticationError"| resolve["_resolve(): walk err.__mro__<br/>until a mapped type is found"]
        resolve --> translate["Rule's translator (structured())<br/>renders {code, message}"]
        translate --> resp1["JSONResponse 401<br/>+ on_error callback (log_info) runs"]

        check -->|"no -- e.g. an unexpected<br/>RuntimeError/KeyError/etc."| unmapped["nothing resolved --<br/>ErrorAwareRoute re-raises"]
        unmapped --> gmw["GlobalExceptionMiddleware<br/>catches it"]
        gmw --> logmetric["logger.exception() +<br/>UNHANDLED_EXCEPTIONS_TOTAL.inc()"]
        logmetric --> gate{"ALERT_ENABLED and<br/>AlertCooldown.should_send()?"}
        gate -->|yes| email["alert email to ALERT_TO_EMAILS"]
        gate -->|no| noemail["no email -- still logged + counted"]
        email --> resp2["JSONResponse 500<br/>(opaque structured() body)"]
        noemail --> resp2

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > The `AuthenticationError` branch is real: it's one of the entries in [`create_user.py`](../../../../src/app/inbound/http/users/create_user.py)'s `error_map` below, mapped to `401 Unauthorized`. The right-hand branch isn't any one specific exception — it's whatever a route's author didn't anticipate, which is the entire point of having a second, unconditional net underneath the first.

## `make_error_aware_router`: the one factory every router goes through

[`router.py`](../../../../src/app/inbound/http/errors/router.py):

```python
def make_error_aware_router(
    *,
    error_map: ErrorMap | None = None,
    on_error: OnError | None = None,
    warn_on_unmapped: bool = True,
    **kwargs: Any,
) -> ErrorAwareRouter:
    return ErrorAwareRouter(
        translator_factory=structured(),
        error_map=error_map,
        on_error=on_error,
        warn_on_unmapped=warn_on_unmapped,
        **kwargs,
    )
```

`ErrorAwareRouter` and `structured` both come from the third-party `fastapi-error-map` package. `ErrorAwareRouter` is a drop-in subclass of FastAPI's own `APIRouter` — every `@router.get/post/put/...` on it accepts an extra `error_map=` keyword that a plain `APIRouter` doesn't. This codebase never instantiates `ErrorAwareRouter` directly; every route file calls `make_error_aware_router()` instead, so `translator_factory=structured()` (see below) and the default `warn_on_unmapped=True` are applied consistently everywhere, rather than repeated — or accidentally varied — file by file.

Under the hood, `ErrorAwareRouter` uses `ErrorAwareRoute` (a subclass of FastAPI's `APIRoute`) as its `route_class`. When a route function raises, `ErrorAwareRoute`'s wrapped handler catches the exception, tries to resolve it against the route's compiled `error_map`, and either returns a translated JSON (JavaScript Object Notation) response or re-raises — which is precisely the `check` decision point in the diagram above.

## `Rule`, `rule()`, and `structured()` — what the library actually provides

An `error_map` entry can be as short as `ExceptionType: 409` — a bare `int` status code — or, when more control is needed, an explicit `Rule`. Reading `fastapi_error_map`'s own source (`rules.py`, `translator_factories/structured.py`) directly, rather than guessing from usage:

- **`Rule`** is a frozen dataclass: `status`, plus optional `translator`, `headers`, `on_error`, and a few `openapi_*` fields. It's the *full* configuration for one mapped exception type — a bare `int` is sugar for `Rule(status=that_int)` with everything else defaulted.
- **`rule(status, ...)`** is the constructor function that builds a `Rule` — this codebase only ever needs it for the one case where the default translator isn't enough (see `HTTP_503_SERVICE_UNAVAILABLE_RULE` below).
- **`structured(...)`** is a *translator factory*: calling it returns a callable that, given an HTTP status, returns a `Translator` — a function `Exception -> StructuredErrorResponse`, where `StructuredErrorResponse` is a `TypedDict` with `code`, an optional `message`, and an optional `details`. By default `code` reads `err.code` (falling back to the status's name, e.g. `"HTTP_404_NOT_FOUND"`), `message` reads `str(err)`, and `details` reads `err.details` — all overridable via keyword arguments to `structured()`. Critically, **`structured()` treats 5xx specially**: for any status `>= 500`, unless the exception's type is explicitly whitelisted via `exposed_5xx_types`, the real exception message is replaced by a fixed `server_message` and `details` is dropped — so a 503/500 body never leaks internal exception text to a client, regardless of what the underlying exception's `str()` happens to say.

[`rules.py`](../../../../src/app/inbound/http/errors/rules.py) is where this codebase reaches for `rule()` once, to get a friendlier message on `503` than the library's default status-name fallback:

```python
SERVICE_UNAVAILABLE_MESSAGE: Final[str] = "Service temporarily unavailable. Please try again later."

HTTP_503_SERVICE_UNAVAILABLE_RULE: Final[Rule] = rule(
    status=status.HTTP_503_SERVICE_UNAVAILABLE,
    translator=structured(server_message=SERVICE_UNAVAILABLE_MESSAGE)(status.HTTP_503_SERVICE_UNAVAILABLE),
)
```

This builds one specific `Translator` — `structured(server_message=...)` returns a factory, and calling that factory with the status pins it to `503` — then wraps it in a `Rule` alongside that same status. Any exception mapped to `HTTP_503_SERVICE_UNAVAILABLE_RULE` (rather than the bare `status.HTTP_503_SERVICE_UNAVAILABLE` int) gets this friendlier `server_message` instead of the library's generic status-name fallback, while still getting the same 5xx-opacity guarantee described above. Being a module-level `Final` constant, it's imported and reused verbatim by every route that can raise a "storage unavailable"/"password hasher busy" style exception, instead of being rebuilt per route.

## The pattern in practice: two real routers, same shape

[`create_user.py`](../../../../src/app/inbound/http/users/create_user.py):

```python
def make_create_user_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            UsernameAlreadyExistsError: status.HTTP_409_CONFLICT,
            EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
            PhoneNumberAlreadyExistsError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_201_CREATED,
        description=getdoc(CreateUser),
    )
    @inject
    async def create_user(
        request: CreateUserRequest,
        interactor: FromDishka[CreateUser],
    ) -> CreateUserResponse:
        return await interactor.execute(request)

    return router
```

[`sign_up.py`](../../../../src/app/inbound/http/account/sign_up.py):

```python
def make_sign_up_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

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
    async def sign_up(
        request: SignUpRequest,
        handler: FromDishka[SignUp],
    ) -> UserQm:
        return await handler.execute(request)

    return router
```

The overlap is the point, not a coincidence: `StorageError`, `BusinessTypeError`, `PasswordHasherBusyError`, and the three `*AlreadyExistsError`s map to the exact same statuses in both routers, because they mean the exact same thing regardless of which use case (a **command**, in this codebase's terms — see [Adding a New Use Case (Command)](../use-case-examples/adding-a-use-case.md)) raised them. What differs is only what's *specific* to each endpoint's own authorization shape — `create_user`'s `AuthenticationError → 401` (an admin-only endpoint needs a valid session first) has no counterpart in `sign_up` (public, unauthenticated by design), while `sign_up`'s `AlreadyAuthenticatedError → 403` (an already-logged-in caller can't sign up again) has no counterpart in `create_user`. `HTTP_503_SERVICE_UNAVAILABLE_RULE` — the shared constant from `rules.py` — is reused by name in both, rather than each router rebuilding an equivalent `rule(...)` call from scratch.

Both routers are also built with `on_error=log_info` ([`callbacks.py`](../../../../src/app/inbound/http/errors/callbacks.py)):

```python
def log_info(err: Exception) -> None:
    logger.info("Handled exception: %s — %s", type(err).__name__, err)
```

`on_error` is a `fastapi-error-map` hook: once a `Rule` resolves for a raised exception, its `on_error` (or, absent one, the router's own default `on_error` passed to `make_error_aware_router`) runs *before* the response is built. `log_info` is deliberately `logging.info`, not a warning or exception log — a mapped `409 Conflict` on a duplicate username is an ordinary, expected outcome of doing business, not a problem to be alerted on; that distinction is exactly what makes Tier 1 different from Tier 2, whose `GlobalExceptionMiddleware` logs at `logger.exception` and can trigger a real alert email. Because `on_error` is attached per `Rule`, a route could in principle give one specific exception type its own callback (e.g. `rule(503, on_error=page_oncall)`) without changing the router-wide default — this codebase doesn't currently need that, but the mechanism supports it.

## Resolution walks the exception's MRO

[`fastapi_error_map`'s `_ErrorHandlingHandler._resolve()`](https://pypi.org/project/fastapi-error-map/) (reading the installed package's `handler.py`) doesn't require an exact type match against `error_map`'s keys — it walks `exc_type.__mro__` (Method Resolution Order, Python's own term for the ordered list of a class and its ancestors it searches for attributes) from the raised exception's own type upward, and returns the first `Rule` whose exception type appears in that chain. Concretely: if a route mapped a base exception class, any subclass of it raised at runtime resolves to that same `Rule`, even though the subclass itself was never mentioned in the `error_map`. If nothing in the whole MRO matches, `_resolve()` returns `None`, `warn_on_unmapped` (on by default from `make_error_aware_router`) logs a warning naming the route and the unmapped type, and the exception is re-raised — which is the `unmapped` branch in the diagram above, continuing on to `GlobalExceptionMiddleware`.

Two more guardrails worth knowing about, both enforced by the library itself rather than by this codebase: `error_map` only accepts 4xx/5xx status codes (anything else raises a `RouteConfigError` at router-construction time), and FastAPI's own framework exceptions — `HTTPException` and `RequestValidationError` — are never intercepted by `error_map` at all, no matter what's mapped; they're rendered by FastAPI before `ErrorAwareRoute`'s wrapper ever sees them. Mapping `422` (FastAPI's own validation-error status) additionally triggers an `ErrorMapWarning` at import time, since it can never actually take effect.

## OpenAPI stays in sync automatically

Because `error_map` is declared once, on the route, `fastapi-error-map` can read it back to build the route's OpenAPI (the machine-readable API (Application Programming Interface) description FastAPI generates, rendered as the interactive Swagger UI at `/docs`) `responses=` entries — grouping every mapped exception by its resulting status and inferring each one's response model from its `Translator`'s return type. A developer adding a new `error_map` entry gets that status documented in Swagger UI for free, without a second, hand-maintained `responses={...}` dict to keep in sync.

That per-route documentation only covers the statuses a route's own `error_map` produces — it says nothing about the *unconditional* possibility of a genuine 500 from Tier 2. [`openapi_responses.py`](../../../../src/app/inbound/http/errors/openapi_responses.py) covers that gap once, for the whole API, instead of per route:

```python
SERVER_ERROR_RESPONSES: Final[OpenApiResponses] = {
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": StructuredErrorResponse},
}
```

[`api_v1_router.py`](../../../../src/app/inbound/http/api_v1_router.py) applies it exactly once, on the top-level `/api/v1` router, via plain FastAPI's own `responses=` kwarg (nothing `fastapi-error-map`-specific here — `APIRouter.responses` merges into every route beneath it):

```python
def make_v1_router(*, cookie_name: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=SERVER_ERROR_RESPONSES)
    router.include_router(make_account_router(cookie_name=cookie_name))
    router.include_router(make_users_router(cookie_name=cookie_name))
    return router
```

So every endpoint's Swagger UI page ends up documenting both halves of this page's two tiers: the specific 4xx/5xx statuses its own `error_map` declares, plus the one generic `500` every endpoint can produce regardless, inherited from this single router-level declaration.

## The same response shape on both tiers

[`internal_server_error.py`](../../../../src/app/inbound/http/errors/internal_server_error.py) is what `GlobalExceptionMiddleware` (Tier 2) actually returns as its JSON body:

```python
def internal_server_error(exc: Exception) -> StructuredErrorResponse:
    translate: Translator[StructuredErrorResponse] = structured()(status.HTTP_500_INTERNAL_SERVER_ERROR)
    return translate(exc)
```

This calls the exact same `structured()` translator factory `make_error_aware_router` uses for Tier 1 — a separate instantiation with the same defaults, not a shared object, but the same shape and the same 5xx-opacity rule described above (no `exposed_5xx_types` passed, so the real exception's message never reaches this body). The practical effect: whether a client gets a `409` from a route's own `error_map` or a `500` from `GlobalExceptionMiddleware` because nothing matched, the JSON envelope is always `{code, message?, details?}` — one consistent contract for API consumers, even though the two responses are produced by completely different code paths.

## Where Tier 2 picks up: `alerting.py`, briefly

[`alerting.py`](../../../../src/app/inbound/http/errors/alerting.py)'s `AlertCooldown` — a per-exception-type, in-memory rate limiter that gates whether `GlobalExceptionMiddleware` emails an on-call address for a given unhandled 500 — is documented in full on [Observability (Prometheus, Grafana, Loki)](../infrastructure-services/observability.md#the-5xx-email-alerting-path). The only thing worth restating here is the boundary this page has been drawing throughout: `AlertCooldown` only ever runs for exceptions that reach `GlobalExceptionMiddleware` in the first place — which, by construction, is exactly the set of exceptions *not* covered by any route's `error_map`. A route that correctly maps `UsernameAlreadyExistsError → 409` will never trigger an alert email for that exception, no matter how often real users hit it; only a genuinely unanticipated failure mode does.

## Where to go next

- [Observability (Prometheus, Grafana, Loki)](../infrastructure-services/observability.md) — `GlobalExceptionMiddleware`, `AlertCooldown`, and the metrics/logging pipeline that Tier 2 feeds.
- [Adding a New REST Endpoint](../use-case-examples/adding-a-rest-endpoint.md) — where `make_error_aware_router` and `error_map` are shown as one step in wiring up a brand-new route.
- [Architecture → Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) — why `inbound/http/errors/` is allowed to import exception types from both `core` and `outbound`, and why the reverse is never true.
