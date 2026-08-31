# API Reference

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/run.py`](../../../src/app/main/run.py) — `make_app()`: the exact `FastAPI(...)` constructor call that sets up `docs_url`/`redoc_url`/`title`/`version`/`summary`/`root_path`
    - [`src/app/main/config/settings.py`](../../../src/app/main/config/settings.py) — `AppSettings` (`SERVICE_NAME`, `VERSION`, `ENVIRONMENT`, `ROOT_PATH`) — the values plugged into the constructor above
    - [`src/app/inbound/http/root_router.py`](../../../src/app/inbound/http/root_router.py) — mounts every router below `/`
    - [`src/app/inbound/http/api_v1_router.py`](../../../src/app/inbound/http/api_v1_router.py) — mounts `account`/`users` under `/api/v1`
    - [`src/app/inbound/http/errors/openapi_responses.py`](../../../src/app/inbound/http/errors/openapi_responses.py) — shared error-response schemas shown in the generated docs
    - [`docs/wiki/content/getting-started/quick-start-docker.md`](getting-started/quick-start-docker.md) / [`quick-start-local.md`](getting-started/quick-start-local.md) — the commands referenced below

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Why there's no separate API reference generator here

This page is deliberately thin. FastAPI already generates a complete, always-current interactive API (Application Programming Interface) reference straight from the real route definitions and Pydantic schemas — building a second, hand-maintained (or separately auto-generated) API reference alongside it would just be another artifact that can silently drift from the real routes. Same principle as the rest of this wiki: generate from the source of truth, don't hand-copy it.

!!! figure "Where the real, always-current API reference actually lives"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        routes["Route + Pydantic schema definitions\n(src/app/inbound/http/**)"] --> openapi["FastAPI's generated OpenAPI schema\n(/openapi.json)"]
        openapi --> docs["Swagger UI\n(/docs)"]
        openapi --> redoc["ReDoc\n(/redoc)"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > Both `/docs` and `/redoc` render the exact same underlying `/openapi.json`, generated live from the route handlers and their request/response models — there is nothing to keep in sync by hand.

## Exactly how Swagger/ReDoc are set up here

There is no custom Swagger/OpenAPI configuration in this codebase beyond three constructor arguments on the single `FastAPI(...)` call in [`make_app()`](../../../src/app/main/run.py) — no custom `openapi()` override, no hand-written schema, no extra Swagger UI theming:

```python
docs_reachable = app_settings.ENVIRONMENT == "development"
app = FastAPI(
    debug=app_settings.DEBUG_MODE,
    title=app_settings.SERVICE_NAME,
    version=app_settings.VERSION,
    summary=f"OpenAPI schema for {app_settings.SERVICE_NAME}",
    lifespan=make_lifespan(),
    root_path=app_settings.ROOT_PATH.rstrip("/"),
    docs_url="/docs" if docs_reachable else None,
    redoc_url="/redoc" if docs_reachable else None,
)
```

- `title` is `AppSettings.SERVICE_NAME` (`APP_SERVICE_NAME` in `env.example`, `fastapi-clean-example` by default) — the same value used for the Compose project name and the Celery app name, see [Configuration → Environment Variables](configuration/environment-variables.md).
- `version`/`summary` come from `AppSettings.VERSION` and are interpolated straight into the summary string — nothing hand-maintained per release.
- `docs_url`/`redoc_url` are set to `"/docs"`/`"/redoc"` only when `ENVIRONMENT=development`; otherwise both are `None`, which is FastAPI's own documented way to disable those two routes entirely (not a 404 handler bolted on afterward — the routes are never registered). `/openapi.json` has no such conditional and is always registered.
- `root_path` is `AppSettings.ROOT_PATH` (empty by default in `env.example`) — set this if the app is deployed behind a reverse proxy on a sub-path, so the URLs Swagger UI generates for "Try it out" stay correct.

## Exactly how to reach it — command and URL (Uniform Resource Locator), for both quick-start paths

| Path | Command that starts the app | Swagger UI URL | ReDoc URL |
|---|---|---|---|
| Docker ([Quick Start with Docker](getting-started/quick-start-docker.md)) | `make upd` | <http://localhost:8000/docs> | <http://localhost:8000/redoc> |
| Local, no Docker for `app` ([Quick Start Locally](getting-started/quick-start-local.md)) | `alembic upgrade head` then `uvicorn app.main.run:make_app --host 0.0.0.0 --port 8000 --reload` | <http://localhost:8000/docs> | <http://localhost:8000/redoc> |

> Both paths land on the same port (`8000`, `UVICORN_PORT` in `env.example`) because both ultimately run the same `make_app()` — the only difference is whether `uvicorn` runs inside the `app` container or directly on your host. Both require `ENVIRONMENT=development` (the `env.example` default) for `/docs`/`/redoc` to be reachable at all — see the next section.

## Reachability by environment

| Environment | `/docs` (Swagger UI) | `/redoc` (ReDoc) | `/openapi.json` |
|---|---|---|---|
| `ENVIRONMENT=development` | Reachable | Reachable | Reachable |
| `ENVIRONMENT=production` | Disabled (route not registered) | Disabled (route not registered) | Reachable |

> `/openapi.json` deliberately stays reachable even in production — e.g. to import the schema into Postman/Insomnia — while the two human-facing doc UIs are switched off, the same dev-only gating principle as Grafana/Adminer/Flower. See [Configuration → Deployment Environments](configuration/deployment-environments.md) for the general `ENVIRONMENT` mechanism, and [Core Patterns → Ports and Adapters](core-patterns/ports-and-adapters.md) for how request/response models map onto the core layer's own entities (Domain-Driven Design term for domain objects with persistent identity — see [Layer Dependencies & Import Rules](architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are)) and query models underneath.

## Where to go next

- **Want the routes explained in context, not just listed?** [Use Case Examples](use-case-examples/adding-a-use-case.md) walks through each endpoint alongside the use case behind it.
- **Curious what a request/response body actually maps to internally?** [Data Models](data-models/domain-entities.md) covers entities, query models, and database models.
- **Need a session cookie to unlock admin-only routes in Swagger UI first?** See "Getting full API (Application Programming Interface) access" in either quick-start page.
