# CLI (Terminal Adapter)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/cli/__main__.py`](../../../../src/app/main/cli/__main__.py) — composition root + entrypoint (`python -m app.main.cli`)
    - [`src/app/main/cli/root_group.py`](../../../../src/app/main/cli/root_group.py) — root Click group, `--username`/`--password` prompt
    - [`src/app/main/cli/identity_provider.py`](../../../../src/app/main/cli/identity_provider.py) — `CliIdentityProvider`, verifies real credentials
    - [`src/app/main/cli/provider.py`](../../../../src/app/main/cli/provider.py) — `CliProvider`, the CLI's own Dishka provider set
    - [`src/app/main/cli/container.py`](../../../../src/app/main/cli/container.py) — build/get/close the CLI's one Dishka container
    - [`src/app/main/cli/errors.py`](../../../../src/app/main/cli/errors.py) — known exceptions → stderr + exit(1)
    - [`src/app/main/cli/users/`](../../../../src/app/main/cli/users/) — the 7 leaf commands
    - [`src/app/core/common/ports/user_finder.py`](../../../../src/app/core/common/ports/user_finder.py) — `UserFinder` port the CLI's identity check needs
    - [`src/app/outbound/adapters/sqla_user_finder.py`](../../../../src/app/outbound/adapters/sqla_user_finder.py) — `SqlaUserFinder` adapter
    - [`docs/plans/6-inbound-cli.md`](../../../../docs/plans/6-inbound-cli.md) — the full implementation plan and design rationale

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this is

The CLI lets every core command/query be invoked directly from a terminal — cron jobs, one-off data seeding/backfills, and admin/ops actions run on a server — with no HTTP/FastAPI involved at all. It reuses the exact same `core` interactors (`CreateUser`, `DeactivateUser`, `ListUsers`, ...) that the HTTP layer calls; only the delivery mechanism differs.

## Why it lives under `main/cli/`, not `inbound/cli/`

This is the one place the CLI's package layout deliberately breaks from HTTP's `inbound`/`main` split, and it's worth understanding why before touching any of these files.

FastAPI's Dishka integration (`setup_dishka(container, app)`, `FromDishka[...]`) bridges the request → container boundary invisibly, entirely from `main.run`'s side — [`src/app/inbound/http/`](../../../../src/app/inbound/http/) never imports anything from `main`. Click has no equivalent invisible bridge: a Click command needs `ctx.obj["container"]` directly, so whatever code builds that container has to be reachable from wherever the command is defined. The Celery worker ([`src/app/main/worker/`](../../../../src/app/main/worker/)) already established the pattern for this in this codebase — DI wiring and adapter code live together under `main/`, with no `inbound/worker/` — and the CLI follows it for the same reason: an earlier draft that put Click commands under `inbound/cli/` (importing `main.cli.container` directly) broke this repo's `clean-architecture` import-linter contract (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)) the first time it was actually run through `make test-docker`.

This is a known, deliberate trade-off, not an oversight — see `docs/plans/0-production-readiness-roadmap.md`'s "Also worth a look before going live" section for the fuller reasoning and a documented (not yet started) follow-up plan to move both the CLI and the worker under `inbound/` together, using a composition-root pattern where `main` imports factory functions from `inbound` instead of the reverse.

## Identity: real authentication, not a trust flag

The CLI prompts for `--username`/`--password` (or reads `APP_CLI_USERNAME`/`APP_CLI_PASSWORD`, mirroring `psql`'s `PGPASSWORD` precedent, for unattended/cron use) and verifies them the same way HTTP login does — `UserService.is_password_valid()` against the real password hash. `CliIdentityProvider` implements the same `IdentityProvider` port `AuthSessionIdentityProvider` implements for HTTP, so every `core` command's existing `current_user_service.get_current_user()` → `authorize(...)` call works unmodified regardless of transport:

```python
async def get_current_user_id(self) -> UserId:
    user = await self._user_finder.find_by_username(Username(self._username))
    # Same error for "no such user" and "wrong password" -- a different
    # message per case would let a caller enumerate valid usernames.
    if user is None or not await self._user_service.is_password_valid(user, RawPassword(self._password)):
        raise CliIdentityError("Invalid username or password.")
    return user.id_
```

## Running it

The `app` service must be up first — `make cli-up` brings the stack up (idempotently; a no-op if it's already healthy) before running your command, so it's the right choice the first time or whenever you're unsure the stack is running. Once it's up, plain `make cli` skips that check for faster repeated invocations, per [Makefile Commands Reference](../development-guide/makefile-commands.md):

```
make cli-up args="users list"
make cli args="users create-user --username jean-grey --email jean@xmen.com --phone-number 27831239999 --role user"
```

Both are thin wrappers around `docker compose exec app python -m app.main.cli $(args)` — this project's standing convention is to never invoke `docker`/`docker compose` directly outside of a `make` target.

## The 7 subcommands

All live under the `users` group (`app.main.cli users <name>`):

| Command | Who can run it | Notes |
|---|---|---|
| `list` | admins | Paginated, sortable; prints JSON |
| `create-user` | admins (only super admins may set `--role admin`) | Prompts for the new user's password |
| `set-user-password` | admins, on subordinate users | Prompts for the new password |
| `grant-admin` | super admins only | |
| `revoke-admin` | super admins only | |
| `activate-user` | admins, on subordinate users | Restores a soft-deleted user |
| `deactivate-user` | admins, on subordinate users | Soft-deletes a user |

Every command's authorization rule is enforced by the same `core` interactor HTTP calls — the CLI adds no new authorization logic, only a new `IdentityProvider`.

## Error handling

`handle_errors` ([`errors.py`](../../../../src/app/main/cli/errors.py)) mirrors HTTP's `error_map` pattern (see [Error Handling (error_map Pattern)](error-handling.md)): a known domain/infrastructure exception becomes a clean stderr message and `exit(1)` instead of a raw Python traceback.

```python
_KNOWN_ERRORS: tuple[type[Exception], ...] = (CliIdentityError, BaseError)


def handle_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except _KNOWN_ERRORS as e:
            click.echo(str(e), err=True)
            raise SystemExit(1) from e

    return wrapper
```

## Testing

CLI tests live under [`tests/integration/with_infra/cli/`](../../../../tests/integration/with_infra/cli/), following [Test Infrastructure & Fixtures](../testing/test-infrastructure.md). Two levels matter here, since they catch different bugs:

- **`click.testing.CliRunner`** invokes `root_group` in-process — fast, and enough to prove each interactor's business logic (authorization, not-found, conflict errors) is wired correctly.
- **A real subprocess** (`subprocess.run([sys.executable, "-m", "app.main.cli", ...])`) proves the actual `python -m app.main.cli` entrypoint works end to end — a real hidden password prompt via `getpass`, a real separate OS process. This distinction mattered in practice: every automated `CliRunner` test passed while the real, manually-invoked entrypoint was silently producing no output at all, because it was being run via `uv run` directly on the host instead of inside the `app` container — see `docs/plans/6-inbound-cli.md`'s Verification Plan for the full story.
