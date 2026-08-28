# Quick Start Locally

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — every command below is a target in here
    - [`scripts/makefile/local_env.sh`](../../../../scripts/makefile/local_env.sh) — generates `.env` for this path specifically, not the same `.env` the Docker path generates
    - [`pyproject.toml`](../../../../pyproject.toml) — the `uv` dependency groups this path installs directly onto your host
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — what `worker`'s Celery command actually is, referenced below

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this path actually is

Not "no Docker at all" — Postgres and Redis still run in Docker (`make upd-local` starts just those two containers, nothing else), but `app` itself runs directly on your host via a plain `uvicorn` process, not a container. This is the path if you want to attach a debugger, iterate without a rebuild step, or just prefer running Python directly. If you'd rather everything run in Docker, including `app`, see [Quick Start with Docker](quick-start-docker.md) instead.

There's no fully-native path in this project's own tooling — nowhere does it script or document installing Postgres/Redis themselves on your host and running them as native processes; Docker Compose is the only way this repo provisions them, on both quick-start paths. That's a deliberate trade: it avoids everyone needing their own local Postgres/Redis install (and keeping its version aligned with what this project expects) just to run the database and cache/broker it depends on. Nothing stops you from installing and running them natively yourself instead — `app` only reads `POSTGRES_HOST`/`REDIS_HOST` and their ports from `.env`, so it doesn't care whether what's listening there is a container or a native process — but that path isn't something this repo sets up or documents for you.

!!! figure "What starts, and which command starts it"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart TB
        updlocal["make upd-local"] --> db_pg[("db_pg")]
        updlocal --> redis[("redis")]
        uvicorn["uvicorn app.main.run:make_app --reload"] --> app["app"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

## What you need installed

**`uv`**, **Python 3.13**, and **Docker** (for Postgres/Redis only). Set up your host environment once:

```shell
uv sync
source .venv/bin/activate
pre-commit install --hook-type pre-commit --hook-type pre-push
```

`uv sync` installs this project's `dev` dependency group locally — everything `make check`/tests/linting need, not just what the app itself needs at runtime.

## One-time setup: secrets

Same requirement as the Docker path: `JWT_SECRET` and `PASSWORD_PEPPER` have no usable default in `env.example` and need a real generated value each, in a `.secrets` file (gitignored) at the repo root:

```shell
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run this twice — once per value, never reusing the same string for both.

> If your `.secrets` already has a `POSTGRES_HOST` or `REDIS_HOST` line from copying an example or an earlier setup, remove or comment it out. `.env` generation is last-value-wins, and this specific path (see below) depends on rewriting those two values — a `.secrets` copy silently undoes that rewrite, and `alembic`/`app` fail to resolve `db_pg` even though `make upd-local` itself looks like it worked. See the comments on `POSTGRES_HOST`/`REDIS_HOST` in `env.example` for the full explanation.

## Starting Postgres and Redis

```shell
make upd-local
```

This generates a **different** `.env` than the Docker path does: `scripts/makefile/local_env.sh` rewrites `POSTGRES_HOST`/`REDIS_HOST` to `127.0.0.1` instead of the Docker-internal service names `db_pg`/`redis` — since `app` runs on your host now, not inside the same Docker network as the database, it has to reach them via a real host port instead of Docker's internal DNS. It only starts `INFRA_SERVICES` (`db_pg`, `redis` — configurable at the top of the `Makefile`), nothing else: **no dev-only dashboards** (Grafana, Prometheus, Adminer, Flower, Redis Commander, this wiki) come up via this path, regardless of `ENVIRONMENT`. If you want those, use the Docker path, or start individual services yourself with plain `docker compose up -d <service>`.

## Running the app

```shell
alembic upgrade head
uvicorn app.main.run:make_app --host 0.0.0.0 --port 8000 --reload
```

Or run [`src/app/main/run.py`](../../../../src/app/main/run.py) directly from your IDE instead of the `uvicorn` command — same entry point, easier to attach a debugger to.

**No `worker` process runs via this path.** `docker-entrypoint.sh`'s `worker` case is just `celery -A app.main.worker.celery_app:celery_app worker --loglevel=INFO --queues=events --concurrency=2` — a plain command you can run yourself in a second terminal if you need to exercise `"background"`-mode event handlers locally. Simpler alternative: set `CELERY_ENABLED=false` in `.secrets` for local work, so every handler runs inline regardless of its own `DISPATCH_MODE` — no worker needed at all. See [Core Patterns → Domain Events & the Transactional Outbox](../core-patterns/domain-events-outbox.md) for what `DISPATCH_MODE` actually controls.

## Getting full API access

Same as the Docker path, minus Adminer (not part of this workflow — connect with `psql -h 127.0.0.1 -p 5432 -U postgres clean-example`, or any Postgres client, using the `POSTGRES_*` values from `env.example`):

1. Create an account via `POST /account/signup/` (or the Swagger UI at `http://localhost:8000/docs`).
2. Set that user's role to `super_admin` directly in the `user` table.
3. Log in via `POST /account/login/` — you now hold a full-access session cookie.

## Stopping

```shell
make down
```

Stops and removes every container `docker compose` knows about for this project — same command, same [known `redis` quirk](https://github.com/ivan-borovets/fastapi-clean-example/blob/master/docs/plans/0-production-readiness-roadmap.md), as the Docker path, since both paths ultimately use the same `docker-compose.yml`.

## Common Make commands

| Command | What it does | Notes |
|---|---|---|
| `make upd-local` | Start Postgres + Redis only, detached | |
| `make up-local` | Same, but attached — logs stream to your terminal | |
| `make down` | Stop and remove every running container | |
| `make check` | Fast: lint, type-check, unit tests — no containers needed | |
| `make test-docker` | Full: integration tests against real Postgres/Redis via Docker | See [Testing → Running Tests](../testing/running-tests.md) |
| `make migration msg=<short description>` | Generate a new Alembic migration | See [Development Guide → Database Migrations](../development-guide/database-migrations.md) |

## Where to go next

- **Prefer everything in Docker, including `app`?** [Quick Start with Docker](quick-start-docker.md).
- **Want to understand what just started?** [Architecture → Layer Dependencies & Import Rules](../architecture/layer-dependencies.md).
- **Contributing code?** See [Development Guide](../development-guide/docker-development.md) and [Testing](../testing/tdd.md) for the day-to-day workflow — linting, TDD, the commit protocol.
