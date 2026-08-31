# Production Deployment

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Dockerfile`](../../../../Dockerfile) — the `ENVIRONMENT` build arg that changes what's installed
    - [`src/app/main/run.py`](../../../../src/app/main/run.py) — `docs_url`/`redoc_url` gating (lines 97-108 as of this writing)
    - [`src/app/main/config/settings.py`](../../../../src/app/main/config/settings.py) — `AppSettings.ENVIRONMENT`, `JwtSettings.SECRET`, `PasswordHasherSettings.PEPPER`
    - [`env.example`](../../../../env.example) — the deliberately-unusable `JWT_SECRET`/`PASSWORD_PEPPER` placeholders
    - [`docs/plans/0-production-readiness-roadmap.md`](../../../../docs/plans/0-production-readiness-roadmap.md) — the honest, up-to-date list of what's still missing

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

**Read this page as "what `ENVIRONMENT=production` changes today," not as "this template is production-hardened."** It genuinely isn't yet — the [Production Readiness Roadmap](../../../../docs/plans/0-production-readiness-roadmap.md) linked throughout this page tracks real, currently-open gaps (no TLS (Transport Layer Security), no rate limiting, secrets in flat files, no backup automation, and more), and this page links to it rather than glossing over them.

## Development vs. production container topology

!!! figure "What actually runs (and what's exposed) under each ENVIRONMENT value"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph devenv["ENVIRONMENT=development (COMPOSE_PROFILES: celery,development,celery-development)"]
            dapp["app\n(/docs, /redoc reachable)"]
            ddb[("db_pg")]
            dcelery["redis, worker"]
            ddash["flower, redis-commander,\nprometheus, grafana, loki,\npromtail, adminer, wiki"]
        end

        subgraph prodenv["ENVIRONMENT=production (COMPOSE_PROFILES: celery only, if CELERY_ENABLED=true)"]
            papp["app\n(/docs, /redoc disabled;\n/openapi.json still reachable)"]
            pdb[("db_pg")]
            pcelery["redis, worker\n(optional)"]
            gap(["No TLS termination, no dashboards,\nno backup automation —\nsee Production Readiness Roadmap"])
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style devenv fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style prodenv stroke-width:1px,stroke:#333333
    ```

    > Every dev-only dashboard (`flower`, `redis-commander`, `prometheus`, `grafana`, `loki`, `promtail`, `adminer`, `wiki`) is behind a Compose profile that requires `ENVIRONMENT=development` (see [Container Orchestration & Profiles](container-orchestration.md)) — it isn't just "not linked from anywhere" in production, the containers themselves never start. `redis`/`worker` are the one exception: they're gated purely by `CELERY_ENABLED`, independent of `ENVIRONMENT`, since Celery is real background-job infrastructure a production deployment may legitimately need too, not dev-only tooling.

## Swagger UI (User Interface) gating, at the code level

!!! figure "run.py's actual docs_url/redoc_url decision"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        envcheck{"AppSettings.ENVIRONMENT"} -->|development| docson["docs_url='/docs'\nredoc_url='/redoc'"]
        envcheck -->|production| docsoff["docs_url=None\nredoc_url=None"]
        docson --> openapi["/openapi.json\n(always reachable, either way)"]
        docsoff --> openapi

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `run.py`'s `make_app()` computes `docs_reachable = app_settings.ENVIRONMENT == "development"` and passes `docs_url="/docs" if docs_reachable else None` (and the same for `redoc_url`) straight into `FastAPI(...)`. `/openapi.json` itself is never gated — only the two interactive HTML (HyperText Markup Language) pages — so a production deployment can still have its schema imported into Postman/Insomnia for testing without exposing a browsable API (Application Programming Interface) explorer publicly.

## What changes, concretely, when `ENVIRONMENT=production`

| Area | `development` | `production` |
|---|---|---|
| Image build (`Dockerfile`) | `uv sync --dev` — installs the full `dev` dependency group (`pytest`, `mypy`, `ruff`, `mkdocs`, `radon`, `pre-commit`, ...) | `uv sync --no-dev` — only runtime dependencies; smaller image, smaller surface |
| Swagger UI / ReDoc | `/docs`, `/redoc` reachable | Both disabled (`None`); `/openapi.json` stays reachable either way |
| Dashboards (`grafana`, `prometheus`, `loki`, `promtail`, `adminer`, `wiki`) | Start automatically (`development` Compose profile active) | Never start — the profile is absent from `COMPOSE_PROFILES` |
| Celery dev UIs (`flower`, `redis-commander`) | Start if `CELERY_ENABLED=true` (`celery-development` profile) | Never start, regardless of `CELERY_ENABLED` — that combined profile requires `ENVIRONMENT=development` too |
| `redis`/`worker` | Start if `CELERY_ENABLED=true` | Start if `CELERY_ENABLED=true` — unaffected by `ENVIRONMENT` |

See [Multi-Stage Docker Build](multi-stage-build.md) for exactly how the `Dockerfile` row above works, and [Container Orchestration & Profiles](container-orchestration.md) for exactly how the Compose-profile rows are computed.

## The `.secrets` requirement

Two settings are deliberately shipped with **unusable** placeholder values in [`env.example`](../../../../env.example): `JWT_SECRET` and `PASSWORD_PEPPER`. Both back a `pydantic` field with `Field(min_length=32)` and no default (`JwtSettings.SECRET`, `PasswordHasherSettings.PEPPER` in [`settings.py`](../../../../src/app/main/config/settings.py)) — so a deployment that never overrides them doesn't get a silently-insecure default, it gets a hard `pydantic.ValidationError` at startup and refuses to run at all. A real deployment must generate a real value for each (e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, run twice, never reusing the same string for both) and place them in a `.secrets` file — gitignored, and layered on top of `env.example` the same way for every environment, not something special to production. See [Getting Started → Quick Start with Docker](../getting-started/quick-start-docker.md#one-time-setup-secrets) for the exact one-time setup steps.

## What's genuinely still missing — read the roadmap

Everything above is real and already working — but it is not the same thing as "ready for production traffic with real user data." The [Production Readiness Roadmap](../../../../docs/plans/0-production-readiness-roadmap.md) is this project's own honest, actively-maintained tracking document for the gap between the two, and it should be read directly rather than summarized-and-forgotten here. As of this writing, its **P0 — floor for any real deployment** tier alone lists:

- Password policy too weak for production use (`RawPassword.MIN_LEN = 6`, no complexity/breach-list check, no upper bound)
- No rate limiting on `/account/login/` or `/account/signup/` — nothing stops credential-stuffing or automated fake-account creation
- Secrets still live in flat `.env`/`.secrets` files, not a real secret store (cloud secrets manager, Vault, etc.)
- No TLS termination anywhere in this stack — every port binds to `127.0.0.1` only, with no reverse-proxy/HTTPS (HyperText Transfer Protocol Secure) setup even as a starting point
- No documented, tested Postgres backup/restore process
- No deploy pipeline past CI (Continuous Integration) — a green build has no automated path to a running deployment, and no rollback mechanism
- No self-service "forgot my password" flow (only an authenticated admin's `set_user_password`, and a logged-in user's own `change_password`)
- No email verification on sign-up
- Known vulnerabilities currently flagged by `pip-audit` (non-blocking today) across `cryptography`, `msgpack`, `pip`, `pydantic-settings`, `pyjwt`, and `starlette`

The roadmap also tracks a **P1** tier (conditional on whether sign-up is public vs. admin-only — CAPTCHA (Completely Automated Public Turing test to tell Computers and Humans Apart)/abuse protection, an admin audit log, MFA (Multi-Factor Authentication), CORS (Cross-Origin Resource Sharing)/security headers) and further items like multi-tenancy and a public API-key auth surface, none of which this page repeats — treat the roadmap document itself as the current source of truth, since it's updated as items get resolved (several already are, and are marked `[x]` there) in a way this static page can't track as reliably.

## Where to go next

- [Container Orchestration & Profiles](container-orchestration.md) — the profile mechanism that gates every dev-only service out of production.
- [Multi-Stage Docker Build](multi-stage-build.md) — how the same `ENVIRONMENT` build arg changes what's actually installed in the image.
- [Configuration → Deployment Environments](../configuration/deployment-environments.md) — the settings-layer view of `development` vs. `production`, alongside `ENVIRONMENT`'s sibling settings.
