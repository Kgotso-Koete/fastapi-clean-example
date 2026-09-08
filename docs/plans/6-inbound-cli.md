# Inbound CLI Adapter

> **Implementation Plan v0.12.0**
>
> Adds `src/app/main/cli/`, so every core command/query can be invoked directly from a terminal script -- cron jobs, one-off data seeding/backfills, and admin/ops actions run directly on a server -- without HTTP/FastAPI involved at all. Closes the open roadmap item of the same name in `docs/plans/0-production-readiness-roadmap.md`.

---

## Why this is safe to add without touching existing composition

This repo already has one precedent for "a non-HTTP entrypoint that still reaches `core` via Dishka DI": the Celery worker (`src/app/main/worker/`). Its `WorkerProvider` (`src/app/main/worker/provider.py`) is a wholly independent `Provider`, deliberately **not** sharing or splitting `CoreProvider` (`src/app/main/ioc/core.py`), because `CoreProvider`'s bindings ultimately need a real Starlette `Request` (`identity_provider = provide(AuthSessionIdentityProvider, ...)` -> `AuthService` -> `CookieManager` -> `Request`, satisfied only by FastAPI's Dishka integration). Dishka validates a provider set's *entire* declared graph at container-build time, so a worker (or CLI) process's provider set must never declare anything that needs a `Request` -- not even indirectly.

This plan follows the exact same shape for a new `CliProvider`: a near-duplicate of `CoreProvider` with one binding swapped (`IdentityProvider` -> a new `CliIdentityProvider` instead of `AuthSessionIdentityProvider`) and one binding added (a new `UserFinder` port, described below). Reused as-is, unmodified: `HasherThreadPoolProvider`, `PersistenceSqlaProvider`, `CeleryProvider` (all `src/app/main/ioc/outbound.py`) -- none of the three needs a `Request`, and the worker already reuses the first two for exactly this reason.

The worker precedent also settles where the CLI's command/adapter code itself lives. HTTP's inbound routers never import anything from `main` -- FastAPI's Dishka integration (`setup_dishka(container, app)`, `FromDishka[...]`) bridges the request/container boundary invisibly, entirely from `main.run`'s side. Click has no equivalent integration, so a Click command that needs the CLI's Dishka container has to import it directly -- which is exactly why the worker keeps its task adapters (`main/worker/tasks.py`) and its DI wiring (`main/worker/provider.py`, `main/worker/container.py`) together under `main/worker/`, with no separate `inbound/worker/` package at all. This plan follows suit: the Click commands/groups live under `main/cli/` alongside `CliProvider`/`build_cli_container()`, not under a new `inbound/cli/`. (An earlier draft of this plan put them under `inbound/cli/`, mirroring HTTP's split; that turned out to violate `pyproject.toml`'s `clean-architecture` import-linter contract -- `inbound` must never import `main` -- the first time it was actually tested against `make test-docker`.)

Authorization itself needs zero new logic: every core command (`GrantAdmin`, `DeactivateUser`, etc.) already calls `self._current_user_service.get_current_user()` then `authorize(...)` as the first thing in `execute()` -- the transport (HTTP today, CLI now) only ever supplies a working `IdentityProvider`. A CLI identity is therefore a DI provider swap, not new authorization code.

**Feature-delete test**: deleting `src/app/main/cli/`, `src/app/core/common/ports/user_finder.py`, and `src/app/outbound/adapters/sqla_user_finder.py` leaves `CoreProvider`, `AuthProvider`, `main/run.py`, and every HTTP file completely unaltered.

## Identity: real username/password authentication, not a trust flag

The CLI prompts for credentials and verifies them with the same mechanism `LogIn` (`src/app/outbound/auth_ctx/handlers/log_in.py`) already uses for HTTP login: `UserService.is_password_valid(user, raw_password)` (`src/app/core/common/services/user.py:80`), which calls the already-bound `PasswordHasher.verify()`. No new password logic -- just a new lookup step, since no existing port resolves "username -> full `User`" outside the unrelated `outbound.auth_ctx` bounded context (`AuthSqlaUserTxStorage.get_by_username`, which `LogIn` uses, is specific to that bounded context and not the right thing to import into a new one). This plan adds one small, CLI-owned port + adapter pair instead:

- `UserFinder` (`src/app/core/common/ports/user_finder.py`): `async def find_by_username(self, username: Username) -> User | None`.
- `SqlaUserFinder` (`src/app/outbound/adapters/sqla_user_finder.py`): queries the primary `AsyncSession` by the mapped `username` column (same session everything else in `CliProvider` uses).

`CliIdentityProvider` (`src/app/main/cli/identity_provider.py`) takes `username: str`, `password: str`, `user_finder: UserFinder`, `user_service: UserService`. `get_current_user_id()`:
1. Looks the user up by username.
2. If not found, **or** `is_password_valid` returns `False` -- raises `CliIdentityError("Invalid username or password.")` (the same message either way, so a wrong password can't be used to enumerate valid usernames).
3. Otherwise returns `user.id_`. (Whether that user is *active* and *authorized* for the specific command is `CurrentUserService.get_current_user()`'s job, exactly as it already is for the HTTP path -- `CliIdentityProvider` only resolves "who is this," not "are they allowed.")

The root Click group prompts for both, interactively by default, with an env-var escape hatch for unattended/cron use (mirroring `psql`'s `PGPASSWORD` precedent):
```python
@click.option("--username", "-u", envvar="APP_CLI_USERNAME", prompt=True)
@click.option("--password", "-p", envvar="APP_CLI_PASSWORD", prompt=True, hide_input=True)
```

## Package layout

Mirrors the worker's own precedent exactly (see "Why this is safe" above): DI wiring and the Click command adapters both live under `main/cli/` -- there is no `inbound/cli/`. All files below are new; nothing existing is modified except `pyproject.toml` (new `click` dependency), `README.md`/this roadmap's checklists (marking the item done), and `Makefile` (one new convenience target).

```
src/app/core/common/ports/user_finder.py            # UserFinder Protocol
src/app/outbound/adapters/sqla_user_finder.py        # SqlaUserFinder

src/app/main/cli/__init__.py
src/app/main/cli/identity_provider.py                # CliIdentityProvider, CliUsername/CliPassword NewTypes, CliIdentityError
src/app/main/cli/access_revoker.py                   # CliAccessRevoker(AccessRevoker) -- see note below
src/app/main/cli/provider.py                         # CliProvider (near-duplicate of CoreProvider), get_cli_providers()
src/app/main/cli/container.py                        # build_cli_container()/get_cli_container()/set_.../clear_.../close_... -- mirrors main/worker/container.py
src/app/main/cli/errors.py                           # handle_errors(): known exceptions -> stderr + exit(1), mirrors HTTP's error_map
src/app/main/cli/root_group.py                       # root_group: root click.Group, --username/--password, composes users group
src/app/main/cli/users/__init__.py
src/app/main/cli/users/group.py                      # make_users_group(): click.Group aggregating the 7 leaf commands below
src/app/main/cli/users/list_users.py
src/app/main/cli/users/create_user.py
src/app/main/cli/users/set_user_password.py
src/app/main/cli/users/grant_admin.py
src/app/main/cli/users/revoke_admin.py
src/app/main/cli/users/activate_user.py
src/app/main/cli/users/deactivate_user.py
src/app/main/cli/__main__.py                         # composition root + entrypoint: `python -m app.main.cli`
```

Each leaf command follows one template (shown once, applied 7 times): a `click.command()` that (1) turns CLI args/options into the interactor's existing request dataclass, (2) runs `asyncio.run(...)` around `async with ctx.obj["container"]() as rc: interactor = await rc.get(TheInteractor); result = await interactor.execute(request)`, wrapped in `@handle_errors`, and (3) `click.echo`s the result (JSON via `json.dumps(..., default=str)` for dict/dataclass results, a plain confirmation line for `None`-returning commands).

`CliProvider` (`src/app/main/ioc/core.py`'s `CoreProvider` mirrored almost verbatim): same `user_service`/`provide_password_hasher`/`provide_email_sender` (`Scope.APP`), same `authz_user_finder`/`utc_timer`/`user_tx_storage`/`flusher`/`tx_manager`/`outbox_repository`/all 6 commands/`user_reader`/`list_users`/`send_welcome_email`/`event_dispatcher`/`provide_handler_registry` (default `Scope.REQUEST`) -- except two swaps:
- `identity_provider = provide(CliIdentityProvider, provides=IdentityProvider)` instead of `AuthSessionIdentityProvider`, plus the new addition `user_finder = provide(SqlaUserFinder, provides=UserFinder)`.
- `access_revoker` (needed by `DeactivateUser`) **cannot** reuse `CoreProvider`'s `AuthSessionAccessRevoker` binding: `AuthSessionAccessRevoker` -> `AuthService` -> `CookieManager` -> `Request` (confirmed by reading `cookie_manager.py`), the exact same "needs a Request" trap `identity_provider` had. But the only method it actually calls, `AuthService.revoke_all_sessions()`, only touches `AuthSessionSqlaTxStorage`/`AuthSqlaTransactionManager` -- both Request-free (they only need the already-reused `AuthAsyncSession`). So this plan adds one more small, self-contained class, `CliAccessRevoker` (`src/app/main/cli/access_revoker.py`), wrapping those two directly instead of going through `AuthService`.

`get_cli_providers()` returns `(CliProvider(), HasherThreadPoolProvider(), PersistenceSqlaProvider(), CeleryProvider())` -- the last three imported straight from `main/ioc/outbound.py`, reused exactly as `WorkerProvider.get_worker_providers()` already reuses the first two (plus `CeleryProvider`, which the worker doesn't need but the CLI does: `CreateUser` calls `EventDispatcher.stage()`/`.dispatch()` -> `HybridEventDispatcher`, which needs `CeleryEnabled`).

## Testing convention

Every existing HTTP inbound test is an integration test against real Postgres (`tests/integration/with_infra/users/test_*.py`) -- `core/commands` itself has 0% unit coverage today, a known, already-tracked roadmap gap. This plan follows the same convention: CLI commands get integration tests using `click.testing.CliRunner` against a real DB-backed container, not mocked unit tests. Only the small new pure-logic pieces (`CliIdentityProvider`'s verify-or-raise logic, the container get/set/clear bookkeeping) get unit tests, mirroring `tests/unit/main/worker/test_container.py`'s exact pattern.

## Proposed Changes

Test file before production file per step, per this project's TDD convention (RED -> GREEN -> refactor).

**Step 1 -- `UserFinder` port/adapter + `CliIdentityProvider`.**
- Test: `tests/unit/main/cli/test_identity_provider.py` -- a fake `UserFinder`/`UserService`; asserts `get_current_user_id()` returns the real `UserId` on a correct username+password, and raises `CliIdentityError` for an unknown username and for a wrong password (same message both times).
- Production: `core/common/ports/user_finder.py`, `outbound/adapters/sqla_user_finder.py`, `main/cli/identity_provider.py`.

**Step 2 -- `CliProvider` + container bootstrap.**
- Test: `tests/unit/main/cli/test_container.py` -- copy of `tests/unit/main/worker/test_container.py`'s get/set/clear/raises-before-init bookkeeping, against `main/cli/container.py`.
- Test: `tests/integration/with_infra/cli/test_container_builds.py` -- builds a real `build_cli_container(username=..., password=...)` against test Postgres and asserts every one of the 7 interactors (plus `CurrentUserService`) resolves inside `async with container() as rc:` without error.
- Production: `main/cli/provider.py`, `main/cli/container.py`.

**Step 3 -- First command end-to-end: `list-users`, plus the shared plumbing every later command reuses.**
- Test: `tests/integration/with_infra/cli/test_list_users.py` -- `CliRunner().invoke(root_group, ["--username", admin.username, "--password", raw_password, "users", "list"])` against a real seeded Postgres; asserts exit code 0 and JSON output, plus: wrong password (exit 1), unknown username (exit 1), and a non-admin actor (exit 1, `AuthorizationError` message).
- Production: `main/cli/errors.py`, `main/cli/root_group.py`, `main/cli/users/group.py`, `main/cli/users/list_users.py`, `main/cli/__main__.py`.

**Steps 4-9 -- remaining 6 commands, one per step, identical shape to Step 3:** `create-user` (4), `set-user-password` (5), `grant-admin` (6), `revoke-admin` (7), `activate-user` (8), `deactivate-user` (9). Each step: one integration test file under `tests/integration/with_infra/cli/test_<name>.py` (happy path + the interactor's real exception cases, e.g. `UserNotFoundError` -> exit 1) written first, then the matching `main/cli/users/<name>.py` file, registered in `users/group.py`.

**Step 10 -- Dependency, docs, and roadmap/README checklist sync.**
- `uv add click` (adds to `[project] dependencies`, updates `uv.lock`) -- done.
- Update `README.md`'s TODO checklist and this roadmap's matching line (`- [ ] Add an inbound CLI ...`) to `- [x] ...`.
- Add `make cli-up args="..."` and `make cli args="..."` Makefile targets -- done, both as `docker compose exec app python -m app.main.cli $(args)`, not the originally-planned `uv run python -m app.main.cli $(ARGS)` on the host. A manual run via host `uv run` was found to silently fail (no output, no error, for both correct and wrong credentials) -- almost certainly a host `.env`/DB-connectivity mismatch, since both an in-process (`CliRunner`) and a real-subprocess reproduction inside the `app` container's own environment work correctly for the same scenarios (see `tests/integration/with_infra/cli/test_list_users.py`'s `test_prompts_for_credentials_*` and `test_real_subprocess_*` tests). `docker compose exec` reuses the already-running, known-good container environment instead, matching this project's existing convention of never invoking `docker`/`docker compose` directly outside of a `make` target. `cli-up` additionally runs `docker compose up -d --wait` first (idempotent -- a no-op if the stack's already healthy) so there's no separate `make upd` step to remember on a first run; plain `cli` skips that for fast repeated invocations once the stack is already up.
- Add wiki documentation for the CLI: invocation, the username/password model, the 7 subcommands.

## File Summary

| File | Purpose |
|---|---|
| `src/app/core/common/ports/user_finder.py` | New port: find a `User` by username |
| `src/app/outbound/adapters/sqla_user_finder.py` | Adapter: `UserFinder` via the primary `AsyncSession` |
| `src/app/main/cli/identity_provider.py` | `CliIdentityProvider`: verifies username/password, returns `UserId` |
| `src/app/main/cli/provider.py` | `CliProvider`: CoreProvider-equivalent for the CLI process |
| `src/app/main/cli/container.py` | Build/get/set/clear/close the CLI's one Dishka container |
| `src/app/main/cli/errors.py` | Exception -> stderr + exit code mapping |
| `src/app/main/cli/root_group.py` | Root `click.Group`, credential prompting, container lifecycle |
| `src/app/main/cli/users/group.py` | `users` subcommand group |
| `src/app/main/cli/users/*.py` | One file per core command/query (7 total) |
| `src/app/main/cli/__main__.py` | `python -m app.main.cli` entrypoint |

## Verification Plan

- `make check` -- lint (`ruff`/`mypy --strict`/`lint-imports`/`slotscheck`) + fast unit tests (Steps 1-2's unit tests).
- `make test-docker` -- full integration suite, including every new `tests/integration/with_infra/cli/test_*.py`.
- `uv run lint-imports` (also part of `make check`) -- confirms `main/cli` respects the existing `clean-architecture` layers contract (no `inbound -> main` edge, since there is no `inbound/cli`); no `pyproject.toml` import-linter changes needed.
- Manual: create an admin via the existing signup+manual-role-promotion flow (`make cli-up` brings the stack up itself if it isn't already running -- sign up through Swagger at http://localhost:8000/docs, promote via Adminer at http://localhost:8080), then run e.g. `make cli-up args="users list"` (prompts for username/password) and, once the stack is confirmed up, plain `make cli args="users deactivate-user <some-user-id>"` for subsequent commands, confirming output and a real DB row change. (See Step 10 for the `cli-up`/`cli` split.)
