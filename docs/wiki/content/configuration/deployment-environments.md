# Deployment Environments (development vs production)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh) — generates `.env` and derives `COMPOSE_PROFILES` from `ENVIRONMENT`/`CELERY_ENABLED`
    - [`docker-compose.yml`](../../../../docker-compose.yml) — every service's `profiles:` gating
    - [`Dockerfile`](../../../../Dockerfile) — `ENVIRONMENT` build arg controlling which `uv` dependency group gets installed
    - [`src/app/main/run.py`](../../../../src/app/main/run.py) — `make_app()`'s `docs_reachable` check, gating `/docs`/`/redoc`
    - [`src/app/main/config/settings.py`](../../../../src/app/main/config/settings.py) — `AppSettings.ENVIRONMENT`, the strictly-validated `Literal["development", "production"]` field
    - [`env.example`](../../../../env.example) — `ENVIRONMENT`'s own header comment, spelling out every consequence of the value

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## One variable, four consumers

`ENVIRONMENT` is deliberately a single, bare (no-prefix) variable — not `APP_ENVIRONMENT` like every other `AppSettings` field — precisely so that the same value can be read directly by shell/build tooling without any of it needing to parse a Python settings object first: `scripts/makefile/docker_env.sh` reads it (to derive `COMPOSE_PROFILES`), and `docker-compose.yml` passes it straight through as a build `ARG` to the `Dockerfile` (to pick a `uv` dependency group). The Python app reads the identical variable a separate way, via `AppSettings.ENVIRONMENT`'s `validation_alias="ENVIRONMENT"` (see [Settings System](settings-system.md)) — four places altogether that key off this one value, none of them needing to agree on a shared parsing mechanism, only on the same two literal strings.

!!! figure "One ENVIRONMENT value, three decision points across the stack"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        envvar["ENVIRONMENT (bare, no prefix)"]

        subgraph shell["docker_env.sh"]
            validate{"exactly 'development'<br/>or 'production'?"}
            derive["derive COMPOSE_PROFILES"]
        end

        subgraph build["Dockerfile (build-time)"]
            depgroup{"ENVIRONMENT build ARG"}
            devdeps["uv sync --dev"]
            proddeps["uv sync --no-dev"]
        end

        subgraph runtime["AppSettings (runtime)"]
            docscheck{"docs_reachable ="}
            docson["/docs, /redoc live"]
            docsoff["/docs, /redoc = None"]
        end

        envvar --> validate
        validate -->|"fail: exit 1"| stop(["ERROR, .env generation aborted"])
        validate -->|"pass"| derive

        envvar --> depgroup
        depgroup -->|"development"| devdeps
        depgroup -->|"production"| proddeps

        envvar --> docscheck
        docscheck -->|"development"| docson
        docscheck -->|"production"| docsoff

        linkStyle default stroke-width:3px,stroke:#333333
        style shell stroke-width:1px,stroke:#333333
        style build stroke-width:1px,stroke:#333333
        style runtime stroke-width:1px,stroke:#333333
    ```

    > All four consumers key off the exact same string, validated independently in two places (`docker_env.sh` and the `Dockerfile` both hard-fail on anything other than `development`/`production` — see below), so a misspelled value is caught at `.env`-generation time or at image-build time rather than silently falling through to some unintended default at runtime.

## `docker_env.sh`: how `COMPOSE_PROFILES` gets derived

[`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh) is invoked by the relevant `Makefile` targets (e.g. `make upd`) before `docker compose` runs. It does three things, in order:

1. **Generate `.env`** by concatenating `env.example` then, if present, `.secrets` (`.secrets` wins on any repeated key — see [Environment Variables](environment-variables.md)).
2. **Validate and derive `COMPOSE_PROFILES`.** It reads `CELERY_ENABLED` and `ENVIRONMENT` back out of the freshly-written `.env`, hard-fails (`exit 1`) unless `ENVIRONMENT` is exactly `development` or `production`, then builds a comma-separated profile list — this exact snippet from [`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh):
   ```bash
   profiles=""
   [ "$celery_enabled" != "false" ] && profiles="${profiles}celery,"
   [ "$environment" = "development" ] && profiles="${profiles}development,"
   if [ "$celery_enabled" != "false" ] && [ "$environment" = "development" ]; then
     profiles="${profiles}celery-development,"
   fi
   ```
   This `COMPOSE_PROFILES` line is appended last, so `.env`'s last-value-wins parsing lets it override anything a user might have (mistakenly) set earlier in `env.example`/`.secrets` — `COMPOSE_PROFILES` is a derived value, never something to set directly.
3. **Render Prometheus/Grafana config templates** (`observability/*.template` → real config files), substituting `APP_SERVICE_NAME` — unrelated to profile derivation, but done in the same script since both need the freshly-generated `.env`.

!!! figure "docker_env.sh's decision logic, in general"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        celeryflag{"CELERY_ENABLED != 'false'?"}
        envflag{"ENVIRONMENT == 'development'?"}

        celeryflag -->|"yes"| addcelery["add 'celery'"]
        celeryflag -->|"no"| skipcelery(["no 'celery',<br/>no 'celery-development' possible"])

        envflag -->|"yes"| adddev["add 'development'"]
        envflag -->|"no"| skipdev(["no 'development'"])

        addcelery --> both{"both conditions true?"}
        adddev --> both
        both -->|"yes"| addcombo["add 'celery-development'"]
        both -->|"no"| nocombo(["skip"])

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > This is why the combined `celery-development` profile is computed explicitly as its own third check, rather than relying on Compose's own profile matching: a single Compose service's `profiles:` list is **OR**-matched against `COMPOSE_PROFILES` (any one match is enough to activate it), so there is no way to express an **AND** of two conditions directly in `docker-compose.yml` — `flower`/`redis-commander` need *both* `CELERY_ENABLED=true` **and** `ENVIRONMENT=development`, so `docker_env.sh` computes that conjunction itself and emits a dedicated profile name for it.

## Which services are gated by which profile

Reading [`docker-compose.yml`](../../../../docker-compose.yml)'s `profiles:` keys directly:

| Profile | Services | Needs |
|---|---|---|
| *(none — always on)* | `app`, `db_pg` | Nothing; these start unconditionally regardless of either setting. |
| `celery` | `redis`, `worker` | `CELERY_ENABLED` != `false` (either `ENVIRONMENT`). |
| `development` | `prometheus`, `grafana`, `loki`, `promtail`, `adminer`, `wiki` | `ENVIRONMENT=development` (regardless of `CELERY_ENABLED`). |
| `celery-development` | `flower`, `redis-commander` | `CELERY_ENABLED` != `false` **and** `ENVIRONMENT=development`, both at once. |

## What actually changes between `development` and `production`

Three independent mechanisms change behavior based on `ENVIRONMENT`, and it's worth being precise that they're three separate switches (all keyed off the same value, but enforced in different files) rather than one:

1. **Which containers start** — the `COMPOSE_PROFILES` derivation above. In `production`, only `app`/`db_pg` (always) and, if `CELERY_ENABLED=true`, `redis`/`worker` run. None of `prometheus`/`grafana`/`loki`/`promtail`/`adminer`/`wiki`/`flower`/`redis-commander` ever start — `env.example`'s own comment on `ENVIRONMENT` is explicit that a real deployment's metrics/log collection is "a separate, deliberately secured decision," since neither Prometheus nor Loki has built-in authentication.
2. **Which `uv` dependency group gets installed into the image** — the [`Dockerfile`](../../../../Dockerfile) takes `ENVIRONMENT` as a build `ARG` (default `production`, overridden by `docker-compose.yml`'s `args: - ENVIRONMENT=${ENVIRONMENT:-development}` for `app`/`worker`/`wiki`), validates it the same way `docker_env.sh` does, and runs `uv sync --frozen --no-cache --dev` for `development` vs. `uv sync --frozen --no-cache --no-dev` for `production` — twice, once with `--no-install-project` for dependency-layer caching and once for the full install. This is also why the `wiki` Compose service (which needs `mkdocs` and its plugins, dev-group-only dependencies) only ever works on a `development`-built image — consistent with it also being restricted to the `development` Compose profile.
3. **Whether `/docs`/`/redoc` are reachable** — [`run.py`](../../../../src/app/main/run.py)'s `make_app()` computes `docs_reachable = app_settings.ENVIRONMENT == "development"` and passes `docs_url="/docs" if docs_reachable else None` (same for `redoc_url`) to the `FastAPI(...)` constructor. Passing `None` for either is FastAPI's own documented mechanism for disabling that page entirely. `/openapi.json` is **not** gated by this check — it stays reachable in both environments, e.g. for importing the schema into Postman/Insomnia — only the interactive HTML (HyperText Markup Language) pages are dev-only.

!!! figure "What ENVIRONMENT=production strips away, relative to development"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph both["Runs in both"]
            app["app"]
            db_pg[("db_pg")]
            openapi["/openapi.json"]
        end

        subgraph condcelery["CELERY_ENABLED=true, either environment"]
            redis[("redis")]
            worker["worker"]
        end

        subgraph devonly["development only"]
            docs["/docs, /redoc"]
            devtools["prometheus, grafana, loki,<br/>promtail, adminer, wiki"]
            devdeps["dev uv dependency group"]
            celerydev["flower, redis-commander<br/>(needs CELERY_ENABLED too)"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style both fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style condcelery stroke-width:1px,stroke:#333333
        style devonly stroke-width:1px,stroke:#333333
    ```

    > Everything in "Runs in both" and "either environment" is unaffected by the `development`/`production` switch — only `CELERY_ENABLED` controls it. Everything in "development only" disappears completely under `ENVIRONMENT=production`: not hidden from navigation, not access-controlled — the containers never start, the routes never get registered (`docs_url=None`), and the dev dependency group is never installed into the image in the first place, so even the packages backing that tooling aren't present to be misused.

## Where to go next

- [Environment Variables (.env / .secrets)](environment-variables.md) — the full reference for `ENVIRONMENT`, `CELERY_ENABLED`, and every other variable these mechanisms read.
- [Settings System (pydantic-settings)](settings-system.md) — how `AppSettings.ENVIRONMENT` is validated once it reaches Python.
- [Getting Started → Quick Start with Docker](../getting-started/quick-start-docker.md) — the `make upd` walkthrough and its own diagram of exactly which containers start with the *default* `env.example` values.
