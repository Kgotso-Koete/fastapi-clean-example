[![Mentioned in Awesome FastAPI](https://awesome.re/mentioned-badge.svg)](https://github.com/mjhea0/awesome-fastapi?tab=readme-ov-file#best-practices)

Stay tuned. Refactor in progress, see [`legacy-2025`](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025) branch for architecture docs

TODO:
- [x] Write tests
- [x] Add `email` and `phone_number` fields to `User` entity with value object validation
- [ ] Explain code and patterns in new README
- [ ] Make template project
- [x] Add domain events infrastructure (`DomainEvent` base class, `EventDispatcher` port, `UserRegisteredEvent`)
- [x] Add email sender port and adapter (`EmailSender` interface with SMTP/console implementations), with multi-recipient (to/cc/bcc) support
- [x] Add event dispatcher with per-handler sync/background dispatch (`EventHandler.DISPATCH_MODE`), background handlers delivered via Celery + Redis
- [x] Send welcome email on user registration as the first domain event use case
- [x] Add a transactional outbox for background event delivery, so a crash between commit and Celery publish can no longer silently drop an event (see `docs/plans/4-transactional-outbox.md`)
- [x] Add observability: structured logging, Prometheus metrics, Grafana dashboards, Loki/Promtail log aggregation, and email alerting on unhandled errors (see `docs/plans/2-observability.md`)
- [ ] Increase test coverage: several `core/commands`/`core/queries` files still have 0% unit coverage (exercised only at the integration level) — see `docs/plans/0-production-readiness-roadmap.md`
- [ ] Add automated coverage gating so a new, untested file/function in `core`/`inbound`/`outbound` fails CI instead of shipping unnoticed (`diff-cover`, or self-hosted SonarQube for an ongoing dashboard) — see `docs/plans/0-production-readiness-roadmap.md`
- [x] Move the remaining hardcoded container host ports (`prometheus`, `grafana`, `loki`, `adminer`) into `env.example`/`.secrets`, matching how the other five services already work
- [x] Make dev-only tooling (`grafana`, `prometheus`, `loki`, `promtail`, `adminer`, and — when Celery is enabled — `flower`, `redis-commander`) conditional on `ENVIRONMENT` (must be exactly `development` or `production`, validated), and stop hardcoding `ENVIRONMENT=development` as a Docker build arg
- [x] Gate Swagger UI (`/docs`, `/redoc`) behind `ENVIRONMENT=development`; `/openapi.json` stays reachable in both, e.g. for importing the schema into Postman/Insomnia
- [x] Centralize the app/service name behind `APP_SERVICE_NAME` for the Compose project/container names, Promtail's log filter, and Prometheus/Grafana's own config (`pyproject.toml`'s name is a documented manual exception — see `docs/plans/0-production-readiness-roadmap.md`)
- [ ] Add a self-hosted documentation wiki (MkDocs + Material, generated dependency-graph and complexity diagrams, no third party) — see `docs/plans/5-self-hosted-docs-wiki.md`
- [ ] Add an inbound CLI (`src/app/inbound/cli/`, sibling to `src/app/inbound/http/`) so core commands/queries can be invoked directly from a terminal script for cron jobs, data seeding, and admin/ops actions, bypassing HTTP entirely — see `docs/plans/0-production-readiness-roadmap.md`
- [ ] Investigate why `docker compose down`/`stop` can fail to remove `worker`/`redis` at all (confirmed in `make test-docker`'s teardown, only `docker kill` recovers it) — see `docs/plans/0-production-readiness-roadmap.md`
- [ ] Harden for production use: password policy, rate limiting, secrets management, TLS, backups, a real deploy pipeline, self-service password reset, email verification, and more — full prioritized backlog in `docs/plans/0-production-readiness-roadmap.md`

Prerequisites
```shell
uv sync
source .venv/bin/activate
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Generate `JWT_SECRET` and `PASSWORD_PEPPER` for `.secrets` (don't reuse the same value for both, and don't commit `env.example`'s `REPLACE_THIS_WITH_...` placeholders as real values):
```shell
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
Run it twice, once per value. `secrets.token_urlsafe(32)` (stdlib, not the `random` module) generates a cryptographically secure, URL-safe string comfortably over both settings' `min_length=32` requirement.

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

**Requires `ENVIRONMENT=development`** — Adminer doesn't start at all in `production`; it's dev-only tooling, not meant to be reachable on a real deployment.

Adminer is included in the docker-compose stack and starts automatically with `make upd`. Access it at **http://localhost:8080** with the following credentials:
- **System**: PostgreSQL
- **Server**: `db_pg` (or `fastapi-clean-example-db_pg-1`)
- **Username**: `postgres`
- **Password**: `password`
- **Database**: `clean-example`

### Observability (Prometheus, Grafana, Loki)

**Requires `ENVIRONMENT=development`** — none of Prometheus, Grafana, Loki, or Promtail start in `production`; neither Prometheus nor Loki has built-in authentication, so this stack isn't meant to run unattended on a real deployment. The app's own `/metrics` endpoint stays reachable regardless of `ENVIRONMENT` — it's just that nothing here is running to scrape/store/visualize it in `production`.

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
- **Critical Error Alerts**: Set `ALERT_ENABLED=true` and `ALERT_TO_EMAILS` (comma-separated; optionally `ALERT_CC_EMAILS`/`ALERT_BCC_EMAILS`) in `.env` to receive email alerts for unhandled 5xx errors (never 4xx validation errors). Rate-limited per exception type via `ALERT_COOLDOWN_S` to prevent inbox flooding during outages.

### Background Events (Celery, Redis)

Domain events are dispatched per-handler: each `EventHandler` declares its own `DISPATCH_MODE` (`"sync"` — awaited inline, blocking the response; or `"background"` — published to Celery, delivered by the `worker` service). See `docs/plans/3-celery-redis-events.md` for the full design.

**Flower/Redis Commander require `ENVIRONMENT=development`** (on top of `CELERY_ENABLED=true`) — they're monitoring dashboards, not infrastructure the app itself needs, so neither starts in `production`. `redis`/`worker` themselves are unaffected by `ENVIRONMENT` and run in both.

- **Flower**: **http://localhost:5555** - inspect task status, retries, and results
- **Redis Commander**: **http://localhost:8081** - browse the raw Redis contents directly: the broker queue (`REDIS_DB`, a Celery message per queued task, gone once consumed) and the result backend (`REDIS_RESULT_DB`, one key per finished task holding its state/return value until it expires)
- **Worker logs**: `docker compose logs -f worker` - see background handlers actually running
- Redis serves as both the Celery broker and result backend (two separate logical databases, `REDIS_DB`/`REDIS_RESULT_DB`)

**Deploying without Celery/Redis** (e.g. to save cost): set `CELERY_ENABLED=false` in `.secrets` (or your deployment's env config) and regenerate `.env` (`make docker-env`/`make local-env`). That's the only setting to change — `redis`/`worker`/`flower` are skipped automatically (`COMPOSE_PROFILES` is derived from `CELERY_ENABLED` and `ENVIRONMENT` together, not something you set directly), and every `"background"`-mode handler runs inline instead — slower (it blocks the response, same as a `"sync"` handler), but still reliably runs, rather than erroring or being dropped.

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
| `wiki-build` | pre-commit | Fails if the wiki (`docs/wiki/`) doesn't build cleanly (`make wiki-build`) |
| `test-docker` | pre-push | Runs the full integration test suite before pushing |
| `no-commit-to-branch` | pre-commit | Blocks direct commits to `main` / `master` |
| `typos` | pre-commit | Catches common spelling mistakes in code and docs |

Thanks for your patience and support

[Acknowledgements](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025?tab=readme-ov-file#acknowledgements)
