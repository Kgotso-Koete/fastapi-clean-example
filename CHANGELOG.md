# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-08-26: Transactional outbox for background event dispatch

### Added
- **Transactional Outbox:** Added `OutboxRepository` port and `SqlaOutboxRepository`/`OutboxMessage` adapters, backed by a new `event_outbox` table (migration `2026-08-21_151755_add_event_outbox_table.py`). `HybridEventDispatcher.stage()` now writes one outbox row per (event, `"background"` handler) pair in the *same* database transaction as the domain change, before commit — closing the dual-write gap where a crash between commit and Celery publish could silently drop an event. A new `app.main.worker.outbox_drain_loop` polls for pending rows on a configurable interval (`CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS`) and relays them to Celery, optionally retaining processed rows (`CELERY_OUTBOX_RETAIN_AFTER_RELAY`). Documented in `docs/plans/4-transactional-outbox.md`.
- **Multi-recipient email:** `EmailSender.send()` now takes `to_emails: Sequence[str]` plus optional `cc_emails`/`bcc_emails`, replacing the old single `to_email`/`to_name` pair. `ALERT_TO_EMAILS`/`ALERT_CC_EMAILS`/`ALERT_BCC_EMAILS` (comma-separated) replace `ALERT_TO_EMAIL`/`ALERT_TO_NAME`.
- **Testing:** `tests/smoke/test_celery_broker.py` gained `test_outbox_row_gets_drained_by_the_real_workers_own_loop`, proving a real, separately-running worker container's own drain loop (not just a producer publishing directly) notices and relays a pending row end-to-end, including verifying it lands correctly in Postgres afterward.
- **Documentation:** Added `docs/plans/0-production-readiness-roadmap.md`, a prioritized backlog of gaps between this template's current state and a real production deployment (auth hardening, secrets/TLS/backups, multi-tenancy considerations, the hardcoded app-name cleanup below, etc.).

### Changed
- **Documentation:** Renamed `docs/implementation-plans/` to `docs/plans/` for a simpler path.

### Fixed
- **Event Dispatch:** `CreateUser`/`SignUp` each called `user.collect_events()` twice — once for `stage()`, once for `dispatch()` — but `collect_events()` drains the entity's event list on every call, so `dispatch()` always received an empty list. This was invisible with `CELERY_ENABLED=true` (`dispatch()` only runs `"sync"`-mode handlers there, and none are registered), but silently broke the `CELERY_ENABLED=false` inline-fallback path: `"background"`-mode handlers like `SendWelcomeEmail` never ran at all, so no email was sent with Celery disabled. Both commands now collect events once and reuse the same list for both calls.
- **API Docs:** `/debug/test-error` had its Swagger tag set both via `include_router(..., tags=["debug"])` and again on the route decorator (`tags=["Debug"]`); FastAPI concatenates rather than overrides tags from the two sources, so the operation carried both and appeared twice in the docs UI. The tag now lives in exactly one place.
- **Test Isolation:** A unit test asserting `CELERY_ENABLED`'s default only cleared the process environment variable, not the `.env` file `load_celery_settings()` also reads directly, so it silently depended on `.env` coincidentally matching the field default. The integration test suite's shared app fixture likewise never pinned `CELERY_ENABLED`, so its outbox-staging assertions silently depended on the ambient `.env`/`.secrets` value rather than the Celery-enabled code path they exist to test. Both are now isolated from ambient configuration explicitly. The real-worker smoke test's wait budget and outcome assertion similarly now derive from the actually configured `CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS`/`CELERY_OUTBOX_RETAIN_AFTER_RELAY` instead of assuming their defaults.

## [0.7.0] - 2026-08-20: Celery + Redis background event dispatch with per-handler control

### Added
- **Domain Events:** `DomainEvent` gained `to_payload()`/`from_payload()` for JSON serialization (`datetime`, `NewType`-over-`UUID`, plain scalars), letting events cross the process boundary to a Celery worker.
- **Ports:** `EventHandler` now declares a required `DISPATCH_MODE: ClassVar[Literal["sync", "background"]]` per handler, replacing the old single global toggle with per-handler control.
- **Adapters:** Added `HybridEventDispatcher`, which awaits `"sync"` handlers inline and publishes `"background"` handlers to Celery by task name. Also added the `build_celery_app` factory and `event_serialization` helpers (`dotted_path`/`import_from_dotted_path`).
- **Worker Process:** New `src/app/main/worker/` composition root for the Celery worker — `loop_runtime` (one persistent asyncio loop per worker process, avoiding "Future attached to a different loop"), `container` (a per-task Dishka `Scope.REQUEST` container over a process-lifetime `Scope.APP` container), `celery_app`, `tasks` (`app.events.dispatch_handler`), and an independent `WorkerProvider` declaring only what registered handlers actually need.
- **Configuration:** Added `RedisSettings` and `CelerySettings` (including `CELERY_ENABLED`, for a Celery-less deployment fallback that runs every handler inline instead), replacing `EventSettings`.
- **Infrastructure:** Added `redis`, `worker`, and `flower` (Celery task monitoring dashboard) services to `docker-compose.yml`, gated behind a `celery` Compose profile derived automatically from `CELERY_ENABLED`. Added `redis-commander` for browsing the actual Redis broker/result-backend contents directly.
- **Testing:** Added a real-broker smoke test (`tests/smoke/test_celery_broker.py`) proving the actual producer→broker→consumer wiring end to end, on top of infra-free unit tests and eager-mode integration tests.
- **Documentation:** Added `docs/implementation-plans/celery-redis-events.md`, documenting the full design plus every issue found and fixed during real `make test-docker`/manual verification runs.

### Changed
- **Event Dispatch:** Migrated `SendWelcomeEmail` to `DISPATCH_MODE = "background"`; it now runs in a real Celery worker process instead of via `asyncio.create_task()`, removing the prior risk of a dropped event on deploy or crash.
- **Docker Compose:** `app` no longer strictly depends on `redis` at startup, so it stays skippable when Celery is disabled.

### Removed
- **Adapters:** Removed `SyncEventDispatcher` and `BackgroundEventDispatcher`, replaced by `HybridEventDispatcher`.
- **Configuration:** Removed the old `EventSettings.DISPATCH_MODE` global env-var toggle.

## [0.6.0] - 2026-08-14: Observability stack with metrics, logs, and alerting

### Added
- **Observability Stack:** Integrated Prometheus, Grafana, Loki, and Promtail via Docker Compose for comprehensive application monitoring and log aggregation.
- **Metrics:** Added `/metrics` endpoint using `prometheus-fastapi-instrumentator` to expose HTTP metrics (request counts, latency histograms, error rates) and custom counters for unhandled exceptions.
- **Structured Logging:** Implemented `JsonFormatter` for structured JSON logging output, configurable via `APP_LOG_FORMAT` environment variable (json/human). Logs include contextual fields like `exception_type`, `path`, `method`, and user information.
- **Alerting:** Added email alerting for unhandled 5xx server errors with rate limiting per exception type via `AlertCooldown` dataclass. Alerts include user context (username, email, phone_number) when authenticated, or anonymous/unknown status otherwise.
- **Configuration:** Added `AlertSettings` with `ALERT_ENABLED`, `ALERT_TO_EMAIL`, `ALERT_TO_NAME`, and `ALERT_COOLDOWN_S` environment variables for alert configuration.
- **Docker Infrastructure:** Added Prometheus, Grafana, Loki, Promtail, and Adminer services to `docker-compose.yml` with automatic provisioning of datasources and dashboards.
- **Testing:** Added comprehensive unit tests for alert cooldown logic and email building, plus integration tests for metrics endpoint, exception counting, email alerting, and rate limiting.
- **Debug Endpoint:** Added `/debug/test-error` endpoint (tagged in Swagger UI) for manual testing of error handling and alerting functionality.

### Changed
- **Exception Handling:** Converted the global exception handler from `@app.exception_handler(Exception)` to a pure ASGI middleware (`GlobalExceptionMiddleware`). This resolves the duplicate traceback logging issue caused by Starlette's `BaseHTTPMiddleware` re-raising exceptions, and correctly integrates user context resolution via `CurrentUserService` for logs and email alerts.
- **Docker Compose:** Modified `make upd` to automatically open observability dashboards (Grafana, Prometheus, Adminer) in the browser after startup.

## [0.5.0] - 2026-08-05: Event dispatcher configuration and logging improvements

### Added
- **Configuration:** Added `EVENT_DISPATCH_MODE` environment variable to dynamically toggle between synchronous and background asyncio event dispatchers at runtime without code changes.
- **Observability:** Replaced standard logging strings with a custom `HumanReadableFormatter`. Injects severity-based emojis (🐛, ℹ️, ⚠️, ❌, 🚨), ANSI color codes, and extra line spacing to drastically improve developer experience when reading server logs.
- **Documentation:** Updated the `README.md` to formally adopt the GitHub CLI (`gh pr`) PR-and-squash workflow, replacing the manual local merge instructions.

## [0.4.0] - 2026-08-05: Domain events and background email dispatching

### Added
- **Domain:** Introduced the `DomainEvent` base class and `UserRegisteredEvent`. Upgraded the base `Entity` class to safely record and flush transient domain events.
- **Architecture:** Implemented the Publish-Subscribe pattern to strictly decouple secondary side-effects (like emails) from core business logic transactions.
- **Ports:** Added `EventHandler`, `EventDispatcher`, and `EmailSender` interfaces to the application core.
- **Adapters (Background Processing):** Created `BackgroundEventDispatcher`, which utilizes `asyncio.create_task` to fire off event handlers concurrently without blocking the main HTTP response. Added `SyncEventDispatcher` for sequential execution (ideal for testing).
- **Adapters (Email):** Created `SmtpEmailSender` (powered by `aiosmtplib` with smart TLS/STARTTLS port negotiation) for production, and `ConsoleEmailSender` for local development.
- **Use Cases:** The `SignUp` and `CreateUser` commands now dispatch a `UserRegisteredEvent` immediately after the primary database transaction successfully commits.
- **Event Handlers:** Added a `SendWelcomeEmail` subscriber that listens for `UserRegisteredEvent` and dispatches an onboarding email in the background.
- **Configuration:** Added comprehensive `EMAIL_*` environment variables. Documented and enforced the `.secrets` file orchestration for overriding local variables without committing them to version control.

## [0.3.0] - 2026-07-30: User contact information fields

### Added
- **Domain:** Added `email` and `phone_number` fields to the `User` domain entity as mandatory parameters.
- **Value Objects:** Added `Email` value object with regex validation and `PhoneNumber` value object for South African numbers with normalization logic.
- **Database:** Added `email` and `phone_number` columns to the `users` table with unique constraints (`uq_users_email`, `uq_users_phone_number`).
- **API:** Updated `CreateUserRequest` DTO to include mandatory `email` and `phone_number` fields.
- **API:** Updated sign-up endpoint to require `email` and `phone_number` in the request payload.
- **Query Model:** Updated `UserQm` to include `email` and `phone_number` fields for read operations.
- **Exceptions:** Added `EmailAlreadyExistsError` and `PhoneNumberAlreadyExistsError` for uniqueness constraint violations.
- **Adapters:** Updated `SqlaFlusher` to map new constraint violations to application exceptions.
- **Adapters:** Updated `SqlaUserReader` to select and map `email` and `phone_number` columns.
- **Handlers:** Updated `LogIn` handler to return `email` and `phone_number` in the response.
- **Tests:** Updated all unit and integration tests to include `email` and `phone_number` in test payloads and assertions.

### Changed
- **Factories:** Updated test factories to generate unique phone numbers using random digit generation instead of UUID hex to ensure valid South African number format.

## [0.2.0] - 2026-07-27: Authentication API enhancements and session security patch

### Added
- **API (Auth):** The `/api/v1/account/signup/` and `/api/v1/account/login/` endpoints now return a sanitized `UserQm` profile (DTO) in the JSON response body instead of an empty payload. This provides frontends (like Angular/React) with immediate access to the authenticated user's ID, username, and role.
- **Tests:** Added explicit integration test assertions in `test_log_in.py` and `test_sign_up.py` to verify the schema of the new DTO response and guarantee that sensitive fields (like `password_hash`) are never leaked.

### Changed
- **API (Auth):** Changed HTTP status code for successful signup and login from `204 No Content` to `200 OK`.
- **Integration Tests:** Updated `tests/integration/with_infra/authentication.py` and test suites to expect `200 OK` rather than `204 No Content`.

### Fixed
- **Security:** Patched a severe session invalidation flaw. The `ChangePassword` handler now forcefully revokes all active database sessions and terminates the local cookie whenever a user changes their password, preventing compromised sessions from remaining active.
- **Data Serialization:** Fixed a bug where Domain Value Objects (`Username` and `UtcDatetime`) were improperly serialized in the API response as string representations (e.g., `Username('name')`) and nested dictionaries. The DTO mapping now correctly extracts the underlying `.value`.

## [0.1.0] - 2025-01-01: Initial project scaffold and core authentication module

### Added
- Initial project scaffolding using Domain-Driven Design, Clean Architecture, and Test-Driven Development principles.
- User management module with basic RBAC (`admin`, `user`).
- Authentication via `HttpOnly` cookies and JWT sessions.
- Dependency Injection architecture using `Dishka`.
- Database integration using `SQLAlchemy` and `Alembic`.
