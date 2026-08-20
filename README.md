[![Mentioned in Awesome FastAPI](https://awesome.re/mentioned-badge.svg)](https://github.com/mjhea0/awesome-fastapi?tab=readme-ov-file#best-practices)

Stay tuned. Refactor in progress, see [`legacy-2025`](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025) branch for architecture docs

TODO:
- [x] Write tests
- [x] Add `email` and `phone_number` fields to `User` entity with value object validation
- [ ] Explain code and patterns in new README
- [ ] Make template project
- [x] Add domain events infrastructure (`DomainEvent` base class, `EventDispatcher` port, `UserRegisteredEvent`)
- [x] Add email sender port and adapter (`EmailSender` interface with SMTP/console implementations)
- [x] Add event dispatcher with per-handler sync/background dispatch (`EventHandler.DISPATCH_MODE`), background handlers delivered via Celery + Redis
- [x] Send welcome email on user registration as the first domain event use case
- [ ] Increase test coverage: add unit tests for domain events and event handlers, integration tests for the full registration-to-email flow, and target comprehensive coverage across all layers
- [ ] Add observability: structured logging, health check improvements, and metrics groundwork

Prerequisites
```shell
uv sync
source .venv/bin/activate
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Start in Docker
```shell
make upd
```

Start locally
```shell
make upd-local
alembic upgrade head
uvicorn app.main.run:make_app --host 0.0.0.0 --port 8000 --reload
# or `src/app/main/run.py` in IDE
```
Full API access:
- create user via sign up
- set its role to `super_admin` manually in DB
- log in as super admin

Stop
```shell
make down
```

Test (light paths)
```shell
make check
```
*Generates unit test coverage report. View in browser at `htmlcov/index.html`*

Test (all paths)
```shell
make test-docker
```
*Generates full integration test coverage report. View in browser at `htmlcov-docker/index.html`*

Generate a migration
```shell
make migration msg=<msg>
```
### Database Management (Adminer)

Adminer is included in the docker-compose stack and starts automatically with `make upd`. Access it at **http://localhost:8080** with the following credentials:
- **System**: PostgreSQL
- **Server**: `db_pg` (or `fastapi-clean-example-db_pg-1`)
- **Username**: `postgres`
- **Password**: `password`
- **Database**: `clean-example`

### Observability (Prometheus, Grafana, Loki)

**What Each Tool Does:**
- **Prometheus**: Time-series database that scrapes and stores metrics from the `/metrics` endpoint every 15 seconds. Provides raw metric data, query language (PromQL), and alerting capabilities.
- **Grafana**: Visualization platform that queries Prometheus for metrics and Loki for logs, displaying them in customizable dashboards. Provides the "App Overview" dashboard with request rates, error rates, latency percentiles, and exception counts.
- **Loki**: Log aggregation system that stores and indexes structured logs from all application containers. Enables powerful log querying and filtering via Grafana.
- **Promtail**: Log agent that scrapes logs from Docker containers, parses them as JSON, and sends them to Loki for storage and indexing.

`make upd` starts a local observability stack alongside the app and automatically opens the key dashboards in your browser:

**Key URLs for Developers:**
- **Grafana Dashboards**: **http://localhost:3000** (login: `admin` / `admin`) - Main visualization interface with pre-configured dashboards for metrics and logs
- **Prometheus**: **http://localhost:9090** - Time-series database for raw metrics querying and alerting rules
- **App Metrics**: **http://localhost:8000/metrics** - Raw Prometheus metrics endpoint (what Prometheus scrapes)
- **Adminer**: **http://localhost:8080** - Database management interface (credentials below)
- **Flower**: **http://localhost:5555** - Celery task monitoring dashboard (see "Background Events" below)
- **Redis Commander**: **http://localhost:8081** - browse the actual Redis keys (see "Background Events" below)

**What's Available:**
- **Metrics Dashboard**: Pre-configured "fastapi-clean-example: App Overview" dashboard with request rate, 5xx error rate, p50/p95/p99 latency, and unhandled exceptions by type
- **Log Aggregation**: Query logs via Grafana (Explore → Loki datasource) using structured queries like `{compose_service="app"} | json | exception_type="ValueError"`
- **Structured Logging**: Set `APP_LOG_FORMAT=json` (default in `env.example`) for filterable logs; `human` for readable terminal output
- **Critical Error Alerts**: Set `ALERT_ENABLED=true` and `ALERT_TO_EMAIL` in `.env` to receive email alerts for unhandled 5xx errors (never 4xx validation errors). Rate-limited per exception type via `ALERT_COOLDOWN_S` to prevent inbox flooding during outages.

### Background Events (Celery, Redis)

Domain events are dispatched per-handler: each `EventHandler` declares its own `DISPATCH_MODE` (`"sync"` — awaited inline, blocking the response; or `"background"` — published to Celery, delivered by the `worker` service). See `docs/implementation-plans/celery-redis-events.md` for the full design.

- **Flower**: **http://localhost:5555** - inspect task status, retries, and results
- **Redis Commander**: **http://localhost:8081** - browse the raw Redis contents directly: the broker queue (`REDIS_DB`, a Celery message per queued task, gone once consumed) and the result backend (`REDIS_RESULT_DB`, one key per finished task holding its state/return value until it expires)
- **Worker logs**: `docker compose logs -f worker` - see background handlers actually running
- Redis serves as both the Celery broker and result backend (two separate logical databases, `REDIS_DB`/`REDIS_RESULT_DB`)

**Deploying without Celery/Redis** (e.g. to save cost): set `CELERY_ENABLED=false` in `.secrets` (or your deployment's env config) and regenerate `.env` (`make docker-env`/`make local-env`). That's the only setting to change — `redis`/`worker`/`flower` are skipped automatically (`COMPOSE_PROFILES` is derived from `CELERY_ENABLED`, not something you set directly), and every `"background"`-mode handler runs inline instead — slower (it blocks the response, same as a `"sync"` handler), but still reliably runs, rather than erroring or being dropped.

See [Makefile](Makefile) for more commands

## How to Commit

This project uses [pre-commit hooks](.pre-commit-config.yaml) that automatically run linting, type checking, vulnerability scanning, and formatting checks before every commit. Committing directly to `main` or `master` is blocked by the `no-commit-to-branch` hook.

### Commit Protocol

**1. Create a feature branch**
```shell
git checkout -b feature/<short-description>
```

**2. Stage and commit your changes using [Conventional Commits](https://www.conventionalcommits.org/)**
```shell
git add .
git commit -m "feat(scope): brief description (vX.Y.Z)"
```

Common prefixes: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

**3. Create a Pull Request**
Use the GitHub CLI to open a PR for review.
```shell
gh pr create --title "feat(scope): brief description" --body "Detailed explanation of changes."
```

**4. Merge and Delete Branch**
Once approved, squash and merge the PR, and automatically delete the feature branch.
```shell
gh pr merge --squash --delete-branch
```

### Pre-commit Hooks Summary

| Hook | Stage | What it does |
|------|-------|-------------|
| `code-check` | pre-commit | Runs linter, formatter, and type checker (`make check`) |
| `pip-audit` | pre-commit | Scans dependencies for known security vulnerabilities |
| `test-docker` | pre-push | Runs the full integration test suite before pushing |
| `no-commit-to-branch` | pre-commit | Blocks direct commits to `main` / `master` |
| `typos` | pre-commit | Catches common spelling mistakes in code and docs |

Thanks for your patience and support

[Acknowledgements](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025?tab=readme-ov-file#acknowledgements)
