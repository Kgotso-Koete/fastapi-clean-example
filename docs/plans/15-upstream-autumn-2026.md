# 15. Bringing in the original author's "Autumn 2026 Updates & Fixes"

> **Status: done (2026-10-07 to 2026-10-09), released as 0.18.0.** Human checks 1 to 5 passed on 2026-10-09; check 6 runs on the pull request. Done before `docs/plans/10-profile-editing.md`, which builds on Step 2's sentinel (decided by the human maintainer, 2026-10-07: "tackle all the upstream code stuff first before editing user profiles to get that out the way").

## Context

The original author's commit https://github.com/ivan-borovets/fastapi-clean-example/commit/5d68d52c9635c7da74d4d45ffb58493f267531aa (2026-10-06, about 100 files) is mostly tooling and refactoring of files this codebase has since built on, so it is **not merged**. This plan brings in the pieces worth having, by hand, one small step at a time. The reasons for what is taken, adapted or left out are in `docs/plans/0-production-readiness-roadmap.md`, "Upstream 'Autumn 2026 Updates & Fixes'".

**How each piece of the original author's code comes in:** before it lands, the AI agent explains in chat what it does and why it's worth having (`agents.md` 5.2), shows the original code and says what, if anything, differs here. The original author's code is ported as written, with this codebase's explanatory comments added (`agents.md` 5.1); it isn't "improved" on the way in.

Not user-facing: this is maintenance under the existing features, so there are no user stories.

**Upstream code changes read line by line and left out** (2026-10-07), because they change style, not behaviour, and would churn files this codebase builds on:
- `auth_ctx/handlers/log_in.py`, `change_password.py`: a password check split into a variable; a constant moved.
- `auth_ctx/service.py`, `sqla_tx_storage.py`: session renewal no longer calls `merge()` on a session SQLAlchemy already tracks. Redundant, not wrong; Step 5's session-renewal test covers the behaviour either way.
- `auth_ctx/id_factory.py`: an unused optional parameter removed.
- `sqla_user_reader.py`: `list_users` renamed `list_all`; the total read with `scalar_one()`.
- `mappings/user.py`: the username's uniqueness written as a named `UniqueConstraint`, with the same name as today, so no schema change.
- `main/setup.py`: `logger.exception` becomes `logger.error(..., exc_info=exc)` in the global exception handler. That fix keeps the traceback when logging outside an `except` block; this codebase replaced that handler with `inbound/http/errors/exception_middleware.py`, which logs inside one, so it doesn't apply.
- `main/ioc/outbound.py`: the engine built by a new `persistence_sqla/engine.py` factory; only its connect-timeout setting is taken (Step 4).

## Proposed changes (each step: test first where there is behaviour to test, confirmed RED, then code, confirmed GREEN)

### Step 1: dependency upgrades

The roadmap's P0 item "bump dependencies with known vulnerabilities flagged by `pip-audit`", using the original author's tested versions as the starting point. Every pin stays exact (`agents.md` 5.3). Each package's changelog is read before bumping, starting with the ones this codebase's auth and routing rely on (`starlette`, `fastapi`, `pyjwt`, `sqlalchemy`).

Done in two halves, so a failure points at one group:

**1a. Runtime dependencies** (upstream → here, today's pin first):
- `alembic` 1.18.4 → 1.20.0
- `fastapi` 0.136.1 → 0.142.2
- `psycopg[binary]` 3.3.4 → 3.3.6
- `pydantic-settings` 2.14.1 → 2.15.0
- `pyjwt[crypto]` 2.12.1 → 2.15.1
- `sqlalchemy[mypy]` 2.0.49 → 2.0.54 (the `[mypy]` extra goes in Step 1c)
- `uuid-utils` 0.15.0 → 1.0.0 (a major version: read its changelog first)
- `uvicorn` 0.46.0 → 0.54.0
- New direct pins, as upstream: `pydantic==2.13.5` and `starlette==1.7.0`, which today arrive only through FastAPI. Pinning them makes the security-relevant versions explicit.
- This codebase's own runtime dependencies that upstream doesn't have (`aiosmtplib`, `celery[redis]`, `click`, `prometheus-fastapi-instrumentator`) are checked with `make pip-audit` and bumped only if it flags them.

**1b. Development tools** (upstream versions where upstream has them):
- `httpx2` 2.5.0 → 2.13.1, `import-linter` 2.11 → 2.15, `mypy` 2.1.0 → 2.4.0, `pip-audit` 2.10.0 → 2.10.1, `pytest` 9.0.3 → 9.1.1, `pytest-asyncio` 1.3.0 → 1.4.0, `ruff` 0.15.12 → 0.16.10, `slotscheck` 0.19.1 → 0.21.0, `tombi` 0.11.3 → 1.7.3 (a major version).
- A newer `ruff` or `mypy` may report things the old one didn't. Each finding is fixed at its cause, never silenced (`agents.md` 4.4 and 5.5).
- Not taken: `prek` (replaces `pre-commit`), `pytest-xdist` (parallel tests, a plan of its own), `shellcheck-py`. `jsonschema` arrives in Step 5, where its test needs it.

**1a result (2026-10-07):** `make check` 479 passed; `make test-docker` 735 passed, plus the 8-step migration stairway. `make pip-audit` no longer lists `starlette`, `pyjwt` or `pydantic-settings`. It still lists eight packages this codebase doesn't pin directly: runtime `anyio`, `cryptography`, `msgpack` and `urllib3`, and dev-only `httpx2`/`httpcore2`, `pip` and `virtualenv`. They are pinned with exact `[tool.uv] constraint-dependencies` in `pyproject.toml` (decided by the human maintainer, 2026-10-07, so every new version is written down, not only in `uv.lock`): `anyio==4.14.2`, `cryptography==50.0.0`, `msgpack==1.2.1`, `pip==26.2`, `urllib3==2.8.0`, `virtualenv==21.7.13`, each the highest fix version `pip-audit` named. A constraint fixes a version without making the package a direct dependency, so `deptry` is unaffected. Done together with 1b, so one `make test-docker` covers both.

**1b result (2026-10-07):** `make pip-audit` reports no known vulnerabilities. The new tools changed some files when `make check` ran:
- **A regression, fixed test first:** ruff 0.16's `LOG004` autofix turned `logger.exception(...)` into `logger.error(...)` in `src/app/inbound/http/errors/exception_middleware.py`, dropping the traceback from every unhandled-500 log line, unnoticed because no test checked it. New test `test_unhandled_exception_is_logged_with_its_traceback` (`tests/integration/with_infra/observability/test_metrics_and_alerting.py`), RED confirmed (`record.exc_info` was `None`), then `logger.error(..., exc_info=exc)`, as upstream does.
- **Harmless:** a type union reordered to put `None` last (`sentinels.py`); a long SQL string wrapped in brackets (`test_rls_spike.py`).
- **Kept (decided by the human maintainer):** ruff now formats Python code blocks inside markdown, so 14 docs had their code examples (never their prose) reformatted.
- **No package was substituted:** `uv.lock` lists the same packages as before plus two new requirements of upgraded ones (`opentelemetry-api` for FastAPI 0.142, `httpx2-jsfetch` for the `httpx2` test client).

**1c. Drop SQLAlchemy's deprecated mypy plugin,** as upstream did: remove `sqlalchemy.ext.mypy.plugin` from `[tool.mypy]` and the `[mypy]` extra from `sqlalchemy`. SQLAlchemy's docs say the plugin is deprecated and "works only up until mypy version 1.10.1" (https://docs.sqlalchemy.org/en/20/orm/extensions/mypy.html); this codebase runs mypy 2.x, so it has likely been doing nothing. It also only understands declarative `Mapped[...]` classes, and every table here is mapped imperatively (`Table` and `map_imperatively`). Dropping the `[mypy]` extra has a side benefit: its only content is `mypy` itself, so as a runtime dependency it put `mypy` into the production image. Any mypy error that appears without it is fixed at its cause, never silenced.

**1c result (2026-10-07):** `make check` 479 passed, mypy still `Success: no issues found`, so the plugin was contributing nothing. `make test-docker` 736 passed, plus the stairway. One earlier run had a single setup `ERROR` (`psycopg` `ConnectionTimeout` in a CLI test) on a run that took 12.5 minutes instead of about 9; the re-run passed, so it was machine load, not this change. **Step 1 is done.**

**What the changelogs say** (read 2026-10-07, before bumping):
- **Security:** Starlette 1.0.1 to 1.3.1 fix five advisories, including GHSA-86qp-5c8j-p5mr (a forged `Host` header changes `request.url.path`, which `exception_middleware.py` and `alerting.py` log: log poisoning here, not an access-control hole). pyjwt 2.13 and 2.14 fix fifteen, mostly in JWK-fetching code this codebase doesn't use (it signs with HS256).
- **Breaking changes that touch this codebase:** none found. FastAPI 0.137's router change only affects code that iterates `.routes`; Starlette 1.7's `BaseHTTPMiddleware` change only affects background tasks; `uuid-utils` 1.0 renames `uuid7()`'s parameters, and this codebase calls it with none (the first test run confirms its return type is unchanged).
- **Low risk:** `pydantic-settings` 2.15 applies `case_sensitive` more widely (settings here are read from prefixed environment variables only); Alembic 1.19.2 stops auto-detecting named CHECK constraint changes (none in the mappings).
- Sources: https://github.com/Kludex/starlette/security/advisories, https://pyjwt.readthedocs.io/en/stable/changelog.html, https://fastapi.tiangolo.com/release-notes/, https://github.com/aminalaee/uuid-utils/releases, https://github.com/pydantic/pydantic-settings/releases, https://alembic.sqlalchemy.org/en/latest/changelog.html.

**Tests:** no new test: an upgrade adds no behaviour. The existing suite is the safety net.

**Commands:** the AI agent edits the pins in `pyproject.toml`; the human maintainer runs `uv lock` to resolve them, then `make check`, `make test-docker` and `make pip-audit`. Expect `pip-audit` to report none of the vulnerabilities the roadmap lists.

### Step 2: the "omitted" sentinel

Lets a `PATCH` tell three states apart for each field: set it, clear it (`null`), or leave it alone (left out). `None` alone can only express two. Plan 10 needs it for the user description, which can be cleared.

- `tests/unit/core/common/test_sentinels.py` (written; RED not yet run), then `src/app/core/common/sentinels.py`: the `Omitted` enum, its `OMITTED` member and `apply_when_present()`.
- `tests/unit/inbound/test_missing.py`, then `src/app/inbound/missing.py`: `omit_if_missing()`, which turns pydantic's `MISSING` (`pydantic.experimental.missing_sentinel`) into `OMITTED`, so `core` never depends on pydantic.
- No route uses them yet; plan 10's `PATCH` routes are the first consumers.
- **Done (2026-10-08):** both RED confirmed (`ModuleNotFoundError`), then GREEN: `make check` 481 passed. The comments in all four files explain what a sentinel is (a one-of-a-kind marker value for a situation, not data, recognised with `is`) as well as what this one is for.

### Step 3: error logs that include the cause

`log_info()` (`src/app/inbound/http/errors/callbacks.py`, the original author's) logs a handled exception's `__cause__` too, so a `503` raised from a database error says which one: `Handled exception: StorageError — ...; caused by: OperationalError — ...`.

- Test: a new `tests/unit/inbound/http/errors/test_callbacks.py` asserting both log lines, with and without a cause (`caplog`), then the change.
- **Deviation from upstream (decided by the human maintainer, 2026-10-08): the cause is logged by type only** (`caused by: OperationalError`), never with its message. Upstream logs the message too, but `SqlaFlusher` raises `StorageError` (503) `from` the SQLAlchemy error in two other places upstream left alone (an unrecognised constraint, any other flush failure), and every mapped error passes through `log_info`. So logging the cause's message would write SQL parameters (email, phone, password hash) into the logs on those 503s. The type name is enough to tell a connection failure from a constraint clash, and can never leak data, whatever raised it.
- **Taken together with it: upstream's `SqlaFlusher` change** (`src/app/outbound/adapters/sqla_flusher.py`, the original author's, still unchanged here). Today a uniqueness clash re-raises `UsernameAlreadyExistsError` (and the email and phone ones) `from e`, the SQLAlchemy `IntegrityError`, and an unrecognised clash is logged as `str(e)`. SQLAlchemy's message includes the SQL statement and its parameters: the new user's email, phone number and password hash. Once `log_info` logs causes, every `409` would write those to the logs. Upstream re-raises `from None` and logs only `e.orig`, the database's own message. OWASP's Logging Cheat Sheet says not to log sensitive data (https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude). Test first: a uniqueness clash's error has no `__cause__`, and the unrecognised-clash warning doesn't contain the statement's parameters. **Deviation:** the warning logs only the violated constraint's name (psycopg's `diag.constraint_name`), not upstream's `e.orig`, because Postgres's message repeats the clashing value in its `DETAIL` line (`Key (email)=(...) already exists.`). Tests: `tests/unit/outbound/adapters/test_sqla_flusher.py`.

**Step 3 done (2026-10-08):** RED confirmed for 3 of the 4 new tests (the fourth pins unchanged behaviour); the captured RED log showed today's warning writing the stand-in email and password hash in full. GREEN: `make check` 485 passed; `make test-docker` 740 passed, plus the stairway, including the existing duplicate-username/email/phone `409` tests through real Postgres.

### Step 4: a configurable database connect timeout

Today `main/ioc/outbound.py` hard-codes `connect_args={"connect_timeout": 5}`. Upstream makes it a setting; here that is `SqlaSettings.CONNECT_TIMEOUT_S` (whole seconds, default `5`, so behaviour is unchanged), set with the environment variable `SQLA_CONNECT_TIMEOUT_S`. Like the other `SQLA_` settings (`SQLA_ECHO`, `SQLA_POOL_SIZE`, ...), it is not listed in `env.example`: they all run on their defaults unless set.

- Tests (done): `tests/unit/main/config/test_loader.py` asserts the new field is read from `SQLA_CONNECT_TIMEOUT_S` and defaults to `5` (`agents.md` 2.3). `tests/unit/main/ioc/test_outbound.py` asserts the engine passes it to the driver: `create_async_engine` is swapped for a recorder, so no timing and no database is involved.
- **Done (2026-10-09):** both RED confirmed (the loader had no `CONNECT_TIMEOUT_S`; the engine still sent `5` when the setting said `7`), then GREEN: `make check` 487 passed.

### Step 4b: don't log the database password

Found while doing Step 4, not from upstream (added by the human maintainer's decision, 2026-10-09). The engine provider in `main/ioc/outbound.py` logs `"Async engine created with DSN: %s"` with `postgres.dsn`, the full connection string, which contains the Postgres password. Anyone running with `APP_LOGGING_LEVEL=DEBUG` writes that password into the logs. OWASP's Logging Cheat Sheet lists passwords and connection strings among the data never to log (https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude).

- Test first, in `tests/unit/main/ioc/test_outbound.py`: with DEBUG logging captured, building the engine never writes the password, and still names the host, port and database, so the line stays useful.
- Then the log line names only `HOST:PORT/DB`, read from `PostgresSettings` (no username, no password).
- **Done (2026-10-09):** RED confirmed (the captured log line held `appuser:s3cret-db-pw@`), then GREEN: both tests in `test_outbound.py` pass. Steps 4 and 4b together: `make check` 488 passed; `make test-docker` passed, plus the 8-step stairway.

### Step 5: tests the original author added for their own features

Upstream changed about 55 test files. Each was read and sorted (2026-10-07): most are reshuffling (renamed fixtures, per-worker test databases for `pytest-xdist`, merged factories) and are not taken. The ones that add checks, compared with this codebase's tests:

**The biggest gap: no test here looks at login sessions in the database.** The production code already does all of this (`AuthService`, `CurrentUserService`, `DeactivateUser` with `AccessRevoker`), but today's tests only check the cookie. In order of value:
1. A user deactivated mid-session gets `403`, and all their sessions are deleted (`test_log_out.py::test_returns_403_and_revokes_sessions_when_user_is_inactive`). Only the API-key side is tested here today (`api_keys/test_inactive_user_revokes_keys.py`).
2. Deactivating a user deletes their sessions (`test_deactivate_user.py::test_returns_204_and_revokes_target_sessions`).
3. A session deleted on the server, or past its expiry, is rejected with `401` (`test_log_out.py::test_returns_401_when_session_is_terminated`, `..._is_expired`).
4. A session close to expiry is renewed: a new cookie, and a later expiry in the database (`users/test_session_renewal.py`).
5. Login creates a session row, and a wrong password, an inactive user or an already-logged-in user creates none; logout deletes the row, not just the cookie (`test_log_in.py`, `test_log_out.py::test_returns_204_and_ends_session`).

**Items 1 to 5 done (2026-10-09): all passed on their first run (no bug found); `make check` 488 passed, `make test-docker` passed, plus the stairway.** Written: `account/test_log_out.py` (items 1, 3 and logout's half of 5), `users/test_deactivate_user.py::test_returns_204_and_revokes_target_sessions` (item 2, which also checks the admin's own session survives), new `users/test_session_renewal.py` (item 4), session-count assertions added to `account/test_log_in.py` (item 5), and `create_auth_session` in `factories.py`.

**A refused request changes nothing:**

6. After every `403`, the state is checked, not just the status: a wrong current password keeps the password; set-password, activate, deactivate, grant and revoke keep the target's password, activation and role; a refused create-user or sign-up creates no user.

**Item 6 done (2026-10-09):** assertions added to eight existing test files; all passed on their first run (no bug found). `test_revoke_admin.py`'s refused targets were changed from plain users to admins, since revoking admin from a plain user changes nothing and the check would have proven nothing.

**Super admins over HTTP** (today only checked at unit level):

7. A super admin can't activate, deactivate, set the password of, grant admin to or revoke admin from another super admin (`403`, nothing changes); a super admin can activate, deactivate and set the password of an admin.

**Item 7 done (2026-10-09):** 8 new tests across the five `users/` route files, plus `create_super_admin` in `factories.py`; all passed on their first run (no bug found).

**Stronger assertions:**

8. A password change is proven by the new password verifying, not just by the stored hash changing (change password, set user password).
9. The users list returns an empty page when the offset is past the total, and checks username, role and activation, not just the id.

**Items 8 and 9 done (2026-10-09):** the three password-success tests now prove the new password verifies (`is_password_valid`); `test_list_users.py` checks the listed user's fields and gains the empty-page test, the first to exercise `SqlaUserReader`'s separate counting path. All passed on their first run (no bug found).

**OpenAPI request-body examples (chosen by the human maintainer, 2026-10-09, over skipping it):**

10. **Corrected 2026-10-09** after reading upstream's files in full: upstream's checker judges only examples that exist (it skips any route without one), and upstream declares no examples, so on upstream's own code its checks run over an empty list. Taken here as upstream wrote it, plus two additions so the checks check something:
    - **Ported as written** (`tests/sanity/inbound/http/`): `request_body_examples.py` (the checker), `test_openapi_request_body_examples.py` (every example valid against its schema, using only its fields, and one per route with all of them), `test_collect_request_body_examples.py` (guards the checker, so it can't go green on an empty list), `test_openapi_trailing_slashes.py`, and the dev pin `jsonschema==4.26.0` (upstream's, in its `dev` group). `conftest.py` is adapted: it builds the OpenAPI document of both apps, the cookie app (`make_fastapi_root_router`) and the public API-key app (`make_public_router`), and every check runs on each.
    - **Added here:** a check that every route with a JSON body declares at least one example (with its own guard test), and then (10b) a realistic example on every request body, declared in `inbound` with `Body(openapi_examples=...)` so `core`'s request types stay untouched. Examples use values that pass this codebase's own rules, because they're what a developer copies from Swagger.
    - **10a (RED):** the tests and the pin; expected to fail only on the new check, listing every route without an example. **10b (GREEN):** the examples.
    - **10a done (2026-10-09):** RED confirmed. The new check listed 9 cookie-app routes and `POST /v1/api-keys/`; the other checks passed (nothing to judge yet); the 13 checker guard tests passed. The trailing-slash test found `/debug/test-error`, the temporary alerting route, the only path without one.
    - **10b done (2026-10-09):** GREEN confirmed (8 example checks, 2 trailing-slash checks); `make check` 511 passed, `make test-docker` passed, plus the stairway, so the 10 routes still accept real bodies through `Body(...)`. Written: one `<ROUTE>_EXAMPLES` constant per route file, passed as `Body(openapi_examples=...)`, with values that pass core's rules; seeded accounts (`peter-parker`, `miles-morales`) where the request acts on existing data, and new X-Men/Avengers names where it creates a user. **Limit, noted so the tests aren't credited with more than they check:** the generated schemas say only "string" or "integer", so the checks catch wrong field names, types and enum values (roles), but not an example that breaks a value object's rules; those values are chosen by hand. The debug route became `/debug/test-error/`, and the `curl` commands in plans 2 and 13 and the wiki's router diagram were updated to match (without the slash they'd now get a `307` redirect, not the `500` they expect).

**How they're ported:** onto this codebase's fixtures (`it_admin`, `it_super_admin`, and `create_user_with_password` followed by `authenticate(...)`), not upstream's renamed `it_authenticated_*` ones. Upstream's `create_auth_session` and `create_super_admin` factories are added to `tests/integration/with_infra/factories.py`. This codebase's login and sign-up answer `200` with a body where upstream answers `204`; only the session and count checks are added, the status codes stay. Before the first session-count assertion, confirm `it_session` sees rows the app committed in its own sessions.

**Not taken:** the health-route tests lose their trailing slash upstream (ours keep `/livez/` and `/healthz/`); `test_settings.py` was deleted upstream only because upstream removed `SessionSettings.ttl`, which this codebase keeps; the 596-line test for upstream's `self_return.py` lint tool.

These test behaviour that already exists, so most pass on their first run; for them, "RED" means checking each one fails when the behaviour is broken, by asking what the assertion would catch. **A test that fails on its first run has found a real bug:** stop, report it, and decide the fix with the human maintainer before going on.

**Step 5 done (2026-10-09):** items 1 to 10; no test found a bug in existing behaviour. The one finding was the trailing-slash test's `/debug/test-error`, fixed in 10b.

### Step 6: a coverage minimum in CI

`make test-docker`'s combined report (`htmlcov-docker/`, 93% today) fails below 75%, as upstream's CI does. Applied to the combined unit and integration run, not `make check`'s unit-only report (71% after Step 5, up from 59%, because item 10's sanity tests build both apps' OpenAPI documents and so import every route module), because adapters are covered by integration tests. A lighter first step toward the roadmap's coverage-gating item.

- No application test: it's build configuration. The human check is a CI run showing the threshold.
- **Done (2026-10-09):** upstream's "Check coverage" step added to `.github/workflows/ci.yaml` as written, after "Test with Docker": `uv run coverage report --data-file=.coverage.docker --fail-under="${MIN_COVERAGE}"` with `MIN_COVERAGE: 75`. Not in `pyproject.toml`'s coverage settings, which would also gate `make check`'s unit-only report. Not taken from upstream's CI file: its `prek` hooks step (Step 1 left `prek` out).

### Step 7: docs and release

`README.md` and roadmap sync (the upstream item done, apart from the parts it adapts or leaves out), wiki updates for anything user-visible (`SQLA_CONNECT_TIMEOUT_S`, the log format), and a `CHANGELOG.md` entry (`agents.md` 1.4).

- **Done (2026-10-09), after the human checks passed** (the human maintainer chose that order: checks, then docs, then commit): `CHANGELOG.md` `[0.18.0]`; `README.md` and the roadmap mark this plan and the P0 `pip-audit` item done (the coverage-gating item stays open, and the debug-route item gains the new path); the wiki covers the connect timeout, cause logging, `SqlaFlusher`'s error handling, request-body examples (a new section in `adding-a-rest-endpoint.md`), the updated `sign_up` code and the CI coverage step. `pyproject.toml`'s `version = "0.2"` is left as it is: it has never tracked the changelog.

## File summary

- **New:** `src/app/core/common/sentinels.py`, `src/app/inbound/missing.py`, and their tests; `tests/unit/inbound/http/errors/test_callbacks.py`; the Step 5 test files.
- **Changed:** `pyproject.toml` and `uv.lock`; `src/app/inbound/http/errors/callbacks.py`; `SqlaSettings`, `main/ioc/outbound.py` (Steps 4 and 4b) and `test_loader.py`; new `tests/unit/main/ioc/test_outbound.py`; `Makefile` or CI for the coverage minimum; docs.

## Verification plan

- `make check` at every GREEN; `make test-docker` after Steps 1, 4, 5 and 6.
- `make pip-audit` after Step 1.
- The human checks below.

## Human checks

Every command's output is human-readable (`agents.md` 1.3).

**Results (2026-10-09): checks 1 to 5 passed.** `pip-audit` found no known vulnerabilities; peter's login, organizations and public-API profile all answered; with the database stopped, login gave `503` and the log line `Handled exception: StorageError — ; caused by: OperationalError`; the engine's log read `Async engine created for db_pg:5432/clean-example`; all 10 routes listed their examples, and the sign-up example worked (tried from `/docs` in the browser). **Note on check 3:** it failed in 0.085 seconds, not about 5. With the container stopped, the hostname `db_pg` doesn't resolve, so the connection fails at once, before the timeout matters; the check proves "fails fast, and says why", and the timeout itself (a host that resolves but doesn't answer) is proven by `test_engine_uses_the_configured_connect_timeout`. The first `make upd` after `make down` reported `db_pg` unhealthy and the second succeeded: Postgres slow to report healthy, unrelated to this plan.

### Setup

1. In `.secrets`, `SEED_DB_WITH_TEST_DATA=true`; `OPEN_DASHBOARDS=` (empty) keeps the browser tabs closed.
2. Start fresh:
   ```shell
   make down
   make upd
   ```
3. Set the Compose project name, from the repo root, in the terminal you'll run the checks in:
   ```shell
   PROJECT=$(grep -h '^APP_SERVICE_NAME=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2)
   PROJECT=${PROJECT:-$(basename "$PWD")}
   echo "$PROJECT"
   ```
   This reads the project name the way the Makefile does (`APP_SERVICE_NAME`, last value wins, else the folder name), so the `docker compose -p "$PROJECT"` commands below look at the containers `make upd` started. Expect your `APP_SERVICE_NAME` printed.

1. **After the upgrades, no known vulnerabilities remain (Step 1).**

   **Why:** the point of Step 1 is closing the vulnerabilities `pip-audit` reported in the roadmap's P0 list.
   ```shell
   make pip-audit
   ```
   Expect no vulnerability reported for `cryptography`, `msgpack`, `pip`, `pydantic-settings`, `pyjwt` or `starlette`. Any line still reported names the package and fix version; note it.

2. **The upgraded app still works end to end (Step 1).**

   **Why:** the test suites prove the code; this proves the running app, with its real web server, does too.

   **Acts on:** peter-parker's account.
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   curl -s -H 'X-API-Key: ak_seed-peter-parker-valid' http://localhost:8000/public/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `200` with peter's profile; his four organizations; then his profile again, through the public API.

3. **With the database down, a request fails fast, and the log says why (Steps 3 and 4).**

   **Why:** Step 4's timeout makes a request give up after `SQLA_CONNECT_TIMEOUT_S` seconds (5) instead of hanging, and Step 3's log line names the underlying database error, so the `503` is diagnosable.

   **Acts on:** the dev stack's `db_pg` container, stopped and then started again.

   Stop only the database, time a login, then read the app's log:
   ```shell
   docker compose -p "$PROJECT" stop db_pg
   time curl -s -w '%{stderr}%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   docker compose -p "$PROJECT" logs app | grep 'caused by'
   ```
   Expect `503` within about 5 seconds (`real` in `time`'s output), then a log line ending `caused by: ...` naming the connection error. Then restore the database:
   ```shell
   docker compose -p "$PROJECT" start db_pg
   ```

4. **The app's log names the database without its password (Step 4b).**

   **Why:** the dev stack runs at `APP_LOGGING_LEVEL=DEBUG` (`env.example`), so before Step 4b every start wrote the Postgres password into the app's log.

   **Acts on:** nothing; it only reads the app's log.
   ```shell
   docker compose -p "$PROJECT" logs app | grep 'Async engine created'
   ```
   Expect lines like `Async engine created for db_pg:5432/...`: a host, port and database name, with no `postgresql+psycopg://`, no username and no password.

5. **Every request body has a documented example, and the sign-up example really works (Step 5, item 10).**

   **Why:** the sanity tests check each example's field names and types against its schema, but the schema only says "string", so they can't tell whether a value passes the real rules (password policy, username, South African phone number). Sending one example exactly as documented proves it does.

   **Acts on:** nothing existing; the sign-up creates a new user, `kitty-pryde`.

   List every route that declares an example, with the example names, for both apps (`/openapi.json` is always served, whatever `ENVIRONMENT` is):
   ```shell
   for doc in openapi.json public/openapi.json; do
     curl -s "http://localhost:8000/$doc" | python3 -c 'import sys, json
   doc = json.load(sys.stdin)
   for path, operations in doc["paths"].items():
       for method, operation in operations.items():
           examples = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("examples")
           if examples:
               print(method.upper(), path, "->", ", ".join(examples))'
   done
   ```
   Expect 10 lines, one per route, for example `POST /api/v1/account/signup/ -> new_user` and `POST /api/v1/account/login/ -> by_username, by_email`, the last being `POST /v1/api-keys/ -> thirty_day_key`. **Prove** `kitty-pryde` doesn't exist yet, by logging in as her:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "kitty-pryde", "password": "PhaseShift2024!"}' | python3 -m json.tool
   ```
   Expect `401`. Then send the sign-up example exactly as `/docs` shows it (no cookie, since a logged-in user can't sign up):
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "kitty-pryde", "password": "PhaseShift2024!", "email": "kitty.pryde@xmen.org", "phone_number": "0821000016"}' | python3 -m json.tool
   ```
   Expect `200` with her new profile: `"username": "kitty-pryde"`, `"role": "user"`, `"is_active": true`, and `"phone_number": "27821000016"` (stored with the country code). A `400` would mean the example breaks a rule. Running this again without a fresh database gives `409`, because she now exists.

6. **CI enforces the coverage minimum (Step 6).**

   **Why:** a gate only counts if the pipeline runs it.

   **Acts on:** the GitHub Actions run for this plan's pull request; checked after the commit, before merging.

   On the pull request, open the CI run's **Check coverage** step. Expect a coverage table ending in a `TOTAL` line above 75% (94% locally on 2026-10-09), and the step to pass.
