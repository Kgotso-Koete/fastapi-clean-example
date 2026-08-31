# Quick Start with Docker

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — every command below is a target in here
    - [`docker-compose.yml`](../../../../docker-compose.yml) — every service this stack starts
    - [`Dockerfile`](../../../../Dockerfile) — the image `app`/`worker`/`wiki` all build from
    - [`env.example`](../../../../env.example) — every environment variable, documented inline
    - [`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh) — generates `.env` and derives `COMPOSE_PROFILES`
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — what each container actually runs on startup
    - [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) — the `wiki-build` hook that catches a broken wiki build before it's committed

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What you actually need installed

Just **Docker and Docker Compose**. Python/`uv` are not required on your host for this path — the image installs everything it needs *inside* the container when it builds. Prefer running the app directly on your host instead (no Docker at all)? See [Quick Start Locally](quick-start-local.md) instead — that's a separate path, not a prerequisite for this one.

## One-time setup: secrets

Two settings are deliberately **not** shipped with a usable default in [`env.example`](../../../../env.example): `JWT_SECRET` and `PASSWORD_PEPPER`. Generate a real value for each and put them in a `.secrets` file (already gitignored) at the repo root:

```shell
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run this twice — once per value, never reusing the same string for both. `.secrets` is a flat `KEY=value` file, same format as `env.example`, that layers on top of it: every command below regenerates the real `.env` by concatenating `env.example` then `.secrets` (`.secrets` wins on any key it repeats), so `env.example`'s own placeholder values never accidentally end up live.

## Starting the stack

Run the `upd` target defined in [`Makefile`](../../../../Makefile):

```shell
make upd
```

This single command: regenerates `.env` from `env.example` + `.secrets`, computes `COMPOSE_PROFILES` from `CELERY_ENABLED`/`ENVIRONMENT`, builds every image, and starts every container whose profile is active. See the Overview's [What actually runs](../../index.md#what-actually-runs) diagram for exactly which containers that is and why. With the defaults in `env.example` (`ENVIRONMENT=development`, `CELERY_ENABLED=true`), that's everything — app, background jobs, and every dev-only dashboard — and `make upd` opens the key ones in your browser automatically.

!!! figure "Which containers `make upd` actually starts, by CELERY_ENABLED / ENVIRONMENT"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 14, "rankSpacing": 5, "padding": 3, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart TB
        start["make upd"] --> app["app"]
        start --> db_pg[("db_pg")]
        start --> env_check{"ENVIRONMENT?"}

        env_check -->|production| celery_prod{"CELERY_ENABLED?"}
        celery_prod -->|true| celery_prod_on((" "))
        celery_prod_on --> redis_prod[("redis")]
        celery_prod_on --> worker_prod["worker"]

        env_check -->|development| dev_on((" "))
        dev_on --> grafana["grafana"]
        dev_on --> prometheus["prometheus"]
        dev_on --> loki["loki"]
        dev_on --> promtail["promtail"]
        dev_on --> adminer["adminer"]
        dev_on --> wiki["wiki"]
        dev_on --> celery_dev{"CELERY_ENABLED?"}

        celery_dev -->|true| celery_dev_on((" "))
        celery_dev_on --> redis_dev[("redis")]
        celery_dev_on --> worker_dev["worker"]
        celery_dev_on --> flower["flower"]
        celery_dev_on --> rediscommander["redis-commander"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > `app`/`db_pg` always start, regardless of either setting. `ENVIRONMENT` is checked first — `CELERY_ENABLED` is checked again inside each branch, since `redis`/`worker` run in *either* environment on their own, while `flower`/`redis-commander` only appear once `ENVIRONMENT=development` **and** `CELERY_ENABLED=true` both hold — that's the `celery-development` profile's AND-condition, shown here by nesting rather than a separate combined check, since a single Compose service's `profiles:` list is OR-matched against `COMPOSE_PROFILES`, not AND-matched.

`scripts/makefile/docker_env.sh` does the first three steps (`.env` generation, `COMPOSE_PROFILES`, config templates); `docker compose` itself does the build and start, respecting every `depends_on`/`healthcheck` already covered in the Overview's container diagram — a container with a failing healthcheck blocks whatever depends on it from starting, rather than starting in a broken state.

| Service | URL (Uniform Resource Locator) | Notes |
|---|---|---|
| App / Swagger UI | <http://localhost:8000/docs> | dev-only; `/openapi.json` stays reachable in production too |
| Adminer (Postgres UI — User Interface) | <http://localhost:8080> | dev-only; System `PostgreSQL`, Server `db_pg`, User `postgres`, Password `password`, DB `clean-example` |
| Grafana | <http://localhost:3000> | dev-only; login `admin` / `admin` |
| Prometheus | <http://localhost:9090> | dev-only |
| Flower (Celery tasks) | <http://localhost:5555> | dev-only, needs `CELERY_ENABLED=true` |
| Redis Commander | <http://localhost:8081> | dev-only, needs `CELERY_ENABLED=true` |
| This wiki | <http://localhost:8001> | dev-only |

> Every port and credential above is the `env.example` default (`${VAR:-default}` in `docker-compose.yml`) — override any of them in `.secrets` if a port collides with something already running on your machine, or before this ever runs somewhere real.

**The wiki container runs `mkdocs serve`** (live-reloading, same as `make wiki` on the host, just containerized on `WIKI_PORT` instead of mkdocs' own default port) — that's what you browse to while it's running; `make upd` doesn't produce a separate static build, and doesn't need to. A `wiki-build` pre-commit hook (`make wiki-build`, see [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml)) catches a broken build before it's committed instead — the same "catch it early, on the host, before it ships" role `code-check`/`pip-audit` already play for the rest of this codebase, not something tied to starting the dev stack.

## Getting full API (Application Programming Interface) access

A fresh database has no users. To reach admin-only endpoints:

1. Create an account via `POST /account/signup/` (or the Swagger UI).
2. In Adminer, manually set that user's role to `super_admin` in the `user` table.
3. Log in via `POST /account/login/` — you now hold a full-access session cookie.

## Common Make commands

Every command mentioned on this page, plus a few more — see [`Makefile`](../../../../Makefile) for the full list (this is deliberately not all of it):

| Command | What it does | Notes |
|---|---|---|
| `make upd` | Start everything, detached (in the background) | |
| `make up` | Same, but attached — logs stream to your terminal, `Ctrl+C` stops everything | |
| `make down` | Stop and remove every running container | `redis` occasionally needs this run twice before it's actually removed — a known, not-yet-diagnosed quirk, tracked in the [production readiness roadmap](https://github.com/ivan-borovets/fastapi-clean-example/blob/master/docs/plans/0-production-readiness-roadmap.md) |
| `make check` | Fast: lint, type-check, unit tests — no containers needed | |
| `make test-docker` | Full: integration tests against real Postgres/Redis via Docker | See [Testing → Running Tests](../testing/running-tests.md) for what each actually covers |
| `make migration msg=<short description>` | Generate a new Alembic migration | See [Development Guide → Database Migrations](../development-guide/database-migrations.md) for how Alembic is wired up here |
| `make wiki` | Serve this wiki locally, outside Docker (live-reload) | |
| `make wiki-build` | One-shot static build of this wiki to `site/`, on your host | runs automatically as a pre-commit hook; needs `uv` installed locally to run by hand |

## Where to go next

- **Prefer not to use Docker at all?** [Quick Start Locally](quick-start-local.md).
- **Want to understand what just started?** [Architecture → Layer Dependencies & Import Rules](../architecture/layer-dependencies.md).
- **Deploying this for real?** [Configuration → Deployment Environments](../configuration/deployment-environments.md) and [Docker and Deployment → Production Deployment](../docker-deployment/production-deployment.md).
