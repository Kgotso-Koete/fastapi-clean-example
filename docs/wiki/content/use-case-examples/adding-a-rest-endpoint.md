# Adding a New REST Endpoint

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/create_user.py`](../../../../src/app/inbound/http/users/create_user.py) — the worked template for this page
    - [`src/app/inbound/http/users/router.py`](../../../../src/app/inbound/http/users/router.py) — how a use case's route joins the `/users` router
    - [`src/app/core/commands/create_user.py`](../../../../src/app/core/commands/create_user.py) — the use case this endpoint wraps
    - [`src/app/inbound/http/errors/router.py`](../../../../src/app/inbound/http/errors/router.py) — `make_error_aware_router`, the `error_map` mechanism
    - [`src/app/inbound/http/errors/callbacks.py`](../../../../src/app/inbound/http/errors/callbacks.py)
    - [`src/app/inbound/http/errors/rules.py`](../../../../src/app/inbound/http/errors/rules.py)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

Once a use case exists as a command in `core` (see [Adding a New Use Case (Command)](adding-a-use-case.md)), exposing it over HTTP (HyperText Transfer Protocol) as a REST (Representational State Transfer) endpoint is a thin, mechanical `inbound` layer step: one small file that declares a route, injects the command, and calls it. [`create_user.py`](../../../../src/app/inbound/http/users/create_user.py) under `inbound/http/users/` is the template below.

## Request flow

!!! figure-wide "HTTP request through to the use case and back"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as FastAPI router\n(make_create_user_router)
        participant Dishka as Dishka\n(@inject / FromDishka)
        participant UseCase as CreateUser\n(core command)
        participant DB as Postgres\n(via ports)

        Client->>Router: POST /users/ (CreateUserRequest JSON)
        Router->>Router: FastAPI validates JSON against\nCreateUserRequest dataclass
        Router->>Dishka: resolve FromDishka[CreateUser]
        Dishka->>UseCase: construct with its ports
        Router->>UseCase: interactor.execute(request)
        UseCase->>DB: authorize, create user, flush, commit
        DB-->>UseCase: success or *AlreadyExistsError
        UseCase-->>Router: CreateUserResponse
        Router-->>Client: 201 Created (CreateUserResponse JSON)

        Note over Router,UseCase: Any exception the use case raises is caught by\nmake_error_aware_router's error_map and turned\ninto the matching HTTP status instead of a 500.
    ```

    > The router file never touches SQLAlchemy, Postgres, or any concrete adapter directly — it only knows about the command's request/response types and the command's own type as a dependency to inject. This is the same inward-pointing-imports rule covered in [Architecture → Layer Dependencies & Import Rules](../architecture/layer-dependencies.md): `inbound` depends on `core`, never the reverse.

## Step 1 — Write the route file

[`create_user.py`](../../../../src/app/inbound/http/users/create_user.py) declares the route:

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

A few details worth calling out explicitly, since each is a deliberate, reusable convention rather than boilerplate:

- **`make_error_aware_router(on_error=log_info)`** wraps a plain `APIRouter`, adding the `error_map=` kwarg to `@router.post(...)`. Every exception type the use case (or anything it calls) might raise is mapped here to the HTTP status it should surface as — this is the *only* place that translation happens; the use case itself never imports `starlette.status`.
- **`description=getdoc(CreateUser)`** pulls the command class's own docstring straight into the OpenAPI/Swagger description — the authorization rules documented once on `CreateUser` (`"Only super admins can create new admins"`, etc.) show up in `/docs` automatically, with nothing duplicated.
- **`@inject` + `FromDishka[CreateUser]`** is [Dishka](../core-patterns/dependency-injection.md)'s per-request dependency injection — the route function declares it needs a fully-constructed `CreateUser`, and Dishka resolves its whole constructor graph (`CurrentUserService`, `UserService`, ports, etc.) without the route function ever seeing any of it.
- **The route function's body is a single line** — `return await interactor.execute(request)`. `interactor` is just this codebase's parameter name for the injected use case (Command) object itself — see [Adding a New Use Case (Command)](adding-a-use-case.md) for what "use case" means here. If a route ever needs more than that, it's usually a sign the extra logic belongs inside the use case, not the route.

## Step 2 — Register the router

`make_create_user_router()` is added to the resource's router in [`router.py`](../../../../src/app/inbound/http/users/router.py):

```python
def make_users_router(*, cookie_name: str) -> APIRouter:
    router = APIRouter(
        prefix="/users",
        tags=["Users"],
        dependencies=[Depends(APIKeyCookie(name=cookie_name))],
    )
    router.include_router(make_create_user_router())
    router.include_router(make_list_users_router())
    # ...
    return router
```

`make_users_router` itself is what carries the shared `/users` prefix, the `Users` Swagger UI tag, and the cookie-auth dependency common to every endpoint under it — a new endpoint on an *existing* resource is just one more `router.include_router(...)` line here. A brand-new resource (a new noun, not a new operation on an existing one) instead gets its own `make_<resource>_router` file, included from wherever the app assembles its top-level router.

## Where to go next

- [Adding a New Use Case (Command)](adding-a-use-case.md) — the prerequisite step this page builds on.
- [Core Patterns → Dependency Injection with Dishka](../core-patterns/dependency-injection.md) — how `@inject`/`FromDishka` resolve a whole object graph per request.
- [Architecture → Inbound Layer (HTTP / Presentation)](../architecture/inbound-layer.md) — the broader conventions this layer follows.
