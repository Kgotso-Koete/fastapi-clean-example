# Password Policy Hardening + Email-Based Login

> Implementation plan for two items from `docs/plans/0-production-readiness-roadmap.md`:
> - Line 21 / paragraph at line 73: "Stronger password policy"
> - Line 50 / paragraph at line 137: "Support logging in via email"
>
> The third roadmap item mentioned alongside these (line 51/140, public API with API-key auth) is explicitly out of scope — the roadmap itself flags it as needing its own dedicated implementation plan, and it is unrelated to these two changes.

## Context

Two gaps were flagged in the roadmap's password/login hardening backlog:

1. **`RawPassword.MIN_LEN = 6`** (`src/app/core/common/value_objects/raw_password.py`) has no lower floor worth calling "secure" and no upper bound at all.
   - Correction to the roadmap's own stated rationale: the roadmap paragraph claims the missing max length is a "latent correctness bug" because "bcrypt silently truncates input past 72 bytes." Verified against `BcryptPasswordHasher` (`src/app/outbound/adapters/bcrypt_password_hasher.py`): the raw password is first run through HMAC-SHA384 and base64-encoded (`_add_pepper`) *before* it ever reaches `bcrypt.hashpw`/`checkpw`, so bcrypt always receives a fixed ~64-byte input regardless of the original password's length. The 72-byte truncation bug does not actually exist in this codebase. A max length is still worth adding as a sane input bound (arbitrary-length input still costs a CPU cycle to HMAC/pepper), just not as a correctness fix.
   - Decision: raise `MIN_LEN` to 12 (NIST 800-63B floor), add `MAX_LEN = 128`, skip the HaveIBeenPwned breach-list check for now (would require an async network call inside what is currently a pure, synchronous value object — every other VO in this codebase is pure; that's a bigger architectural change better left to its own follow-up).
   - Follow-up decision: also add a composition rule (at least one letter, one digit, one special character from an allowlist). Neither NIST 800-63B nor OWASP's Authentication Cheat Sheet actually recommend forced composition — both prefer length plus a breach/blocklist check. It was added anyway for a reason those guidelines don't have to weigh: composition/length checks are pure, synchronous, and local, so they can't fail due to a third-party outage, rate limit, or added latency on the auth path, unlike a HaveIBeenPwned-style check. The two are complementary: composition/length reliably rejects trivially weak local patterns (e.g. `aaaaaaaaaaaaaa`) with zero external dependency, while a breach-list would additionally catch known-compromised passwords that pass composition but are still common (e.g. `Password1!`).

2. **`LogIn` only supports username lookup** (`src/app/outbound/auth_ctx/handlers/log_in.py` calls `AuthSqlaUserTxStorage.get_by_username` only), even though `User` already has a validated, unique `email` field — no entity change needed.
   - Decision: no `LOGIN_METHOD` env var. Instead, a single renamed `identifier` field on `LogInRequest` that accepts either a username or an email, auto-detected by attempting `Email(identifier)` first and falling back to `Username(identifier)` on `BusinessTypeError`. This avoids a deploy-time config knob that has to stay in sync with the frontend, and lets any user log in with whichever identifier they remember.
   - Session/token issuance is unaffected — JWT/`AuthSession` are keyed on the internal `UserId`, never on username or email.

## TDD Methodology

Strict red-green, one dependency-chain at a time: write the test file, run it, confirm it fails for the expected reason (RED), only then write the minimum production code to pass it (GREEN). No test file and its production file are written without a real run in between.

---

## Step 1 — Password policy (`RawPassword`)

**Files:** `tests/unit/core/common/value_objects/test_raw_password.py` (MODIFY), `src/app/core/common/value_objects/raw_password.py` (MODIFY)

Added tests asserting `MIN_LEN == 12`, `MAX_LEN == 128`, acceptance at the max boundary, and rejection above it. Existing boundary tests already parametrize off `RawPassword.MIN_LEN` dynamically, so they kept working once the constant changed.

Production: extended `_validate` with the same `ClassVar` pattern already used for `MIN_LEN`, adding a symmetric `MAX_LEN` check.

**Follow-up (composition rule):** added tests rejecting a password missing a letter, missing a digit, and missing a special character, plus a test iterating every character in the new `SPECIAL_CHARS` allowlist. Production added `SPECIAL_CHARS: ClassVar[str] = "!@#$%^&*()_+-=[]{}|;:,.<>?"` and three more checks in `_validate` (letter/digit/special-char presence, via `any(...)` over the string).

This broke every test relying on `create_raw_password()`'s default (`uuid.uuid4().hex` — letters and digits, but no special character) and several literal password strings across the suite that were missing a digit and/or special character (`"secure"`, `"bruteforce"`, `"x" * 73`, `"raw_password"`, `"test-password"` ×3, `"wrong-password"` ×2). Fixed the two `create_raw_password` factory defaults (`tests/unit/core/common/services/factories.py`, `tests/integration/with_infra/factories.py`) by appending a special character, and updated each literal to include a missing digit/special char while preserving its original test intent.

A first sweep only searched for direct `RawPassword(...)`/`create_raw_password(...)`/`CliPassword(...)` construction and missed passwords that reach `RawPassword` indirectly via CLI `input=`/`--password` values in `tests/integration/with_infra/cli/`: `"definitely-the-wrong-one"` (missing digit, used across `test_identity_provider.py` and `test_list_users.py`) and `"a-brand-new-password"` (missing digit, used in `test_create_user.py` and `test_set_user_password.py`). Both fixed the same way (append a digit). `"irrelevant1"` (also used in these files) was investigated and left as-is — it's passed for an unknown-username case, and `CliIdentityProvider.get_current_user_id()`'s `user is None or ...` short-circuits before `RawPassword` is ever constructed for it.

---

## Step 2 — Identifier resolution (`LogIn` handler, pure logic)

**Files:** `src/app/outbound/auth_ctx/handlers/log_in.py` (MODIFY)

Renamed `LogInRequest.username` → `identifier`, and added a private static helper:

```python
@staticmethod
def _resolve_identifier(identifier: str) -> Email | Username:
    try:
        return Email(identifier)
    except BusinessTypeError:
        return Username(identifier)
```

(Matches the existing `_add_pepper` static-helper convention in `BcryptPasswordHasher`.)

A unit test that called `LogIn._resolve_identifier(...)` directly was tried first, but Ruff's `SLF001` flagged it as a private-member access from outside the class — correctly. Checking `tests/unit/outbound/test_bcrypt_password_hasher.py` (which tests `BcryptPasswordHasher`, whose own `_add_pepper` is the same kind of private static helper) confirmed the original author's actual convention: private logic is verified through the class's public interface, never accessed directly from a test (`test_supports_passwords_longer_than_bcrypt_limit` covers `_add_pepper`'s exact effect via `hash()`/`verify()`, not by touching `_add_pepper`). So no unit test was added for `_resolve_identifier`; its behavior is instead covered by the integration tests in Step 4, matching the fact that `LogIn` had zero unit tests before this change.

---

## Step 3 — Storage lookup by email + wire the dispatch

**Files:** `src/app/outbound/auth_ctx/sqla_user_tx_storage.py` (MODIFY), `src/app/outbound/auth_ctx/handlers/log_in.py` (MODIFY — `execute()`)

No dedicated unit test: storage/adapter classes in this codebase have no unit tests anywhere in the repo — they're only exercised through integration tests against the real DB.

Added `get_by_email` to `AuthSqlaUserTxStorage`, a near-copy of `get_by_username` (same `for_update` parameter, swaps `users_table.c.username` for `users_table.c.email`). `LogIn.execute()` now dispatches on the resolved identifier's type:

```python
identifier = self._resolve_identifier(request.identifier)
password = RawPassword(request.password)
if isinstance(identifier, Email):
    user = await self._user_tx_storage.get_by_email(identifier)
else:
    user = await self._user_tx_storage.get_by_username(identifier)
if user is None:
    raise AuthenticationError
```

---

## Step 4 — Integration tests (end-to-end RED/GREEN for the login change)

**File:** `tests/integration/with_infra/account/test_log_in.py` (MODIFY), plus the shared `tests/integration/with_infra/authentication.py` helper (its payload key needed the same rename).

- Renamed every existing payload key from `"username"` to `"identifier"` (7 existing tests; response-body assertions on `data["username"]` are unaffected — that's the response shape, not the request).
- Added one new case: logging in successfully using the user's **email** as `identifier` (asserts 200 + cookie, same as the existing username-based success case).

This was the real RED step for the storage + dispatch wiring: writing these test changes first (with Steps 2's rename/resolver already in place) surfaced a 400 "Username must be between 5 and 20 characters" failure on the new email-login test, confirming `execute()` still treated the identifier as a username-only value. Applying Step 3's storage + dispatch changes turned it GREEN — 355 passed via `make test-docker`.

---

## Step 5 — Documentation

- `docs/wiki/content/use-case-examples/account-log-in.md` (MODIFY) — updated the prose, sequence diagram, and Step 2 code excerpt to reflect identifier resolution and both lookup paths.
- `docs/plans/0-production-readiness-roadmap.md` (MODIFY) — checked off the two checklist lines and rewrote the two narrative paragraphs to `**Done.**` summaries, matching the existing convention used for other completed items on that list.
- `README.md` — no change. Its one relevant TODO line is an umbrella bullet covering several still-open hardening items (rate limiting, secrets management, TLS, backups, self-service password reset, email verification) and stays unchecked until all of them are done.

---

## File Summary

| Action | File |
|---|---|
| Modify | `src/app/core/common/value_objects/raw_password.py` |
| Modify | `tests/unit/core/common/value_objects/test_raw_password.py` |
| Modify | `src/app/outbound/auth_ctx/handlers/log_in.py` |
| Modify | `src/app/outbound/auth_ctx/sqla_user_tx_storage.py` |
| Modify | `tests/integration/with_infra/account/test_log_in.py` |
| Modify | `tests/integration/with_infra/authentication.py` |
| Modify | `docs/wiki/content/use-case-examples/account-log-in.md` |
| Modify | `docs/plans/0-production-readiness-roadmap.md` |
| Modify | `tests/unit/core/common/services/factories.py` (`create_raw_password` default) |
| Modify | `tests/integration/with_infra/factories.py` (`create_raw_password` default) |
| Modify | `tests/unit/outbound/test_bcrypt_password_hasher.py` (literal passwords) |
| Modify | `tests/performance/profile_bcrypt_password_hasher.py` (literal password) |
| Modify | `tests/unit/core/common/services/test_user.py` (literal passwords) |
| Modify | `tests/unit/core/common/services/test_stubs.py` (literal passwords) |
| Modify | `tests/unit/main/cli/test_identity_provider.py` (literal password) |
| Modify | `tests/integration/with_infra/cli/test_create_user.py` (literal password) |
| Modify | `tests/integration/with_infra/cli/test_set_user_password.py` (literal password) |
| Modify | `tests/integration/with_infra/cli/test_list_users.py` (literal password) |

No changes needed to: `User` entity (already had `email`), `Email`/`Username` value objects, DI wiring (`AuthProvider` auto-wires via type annotations, no explicit `provides=`), inbound router (`LogInRequest` dataclass *is* the request schema — no separate Pydantic model to update), session/JWT issuance.

## Verification Plan

**Automated:**
```bash
uv run pytest tests/unit/core/common/value_objects/test_raw_password.py -v
make test-docker   # full integration + migrations suite against real Postgres
make check         # linting, type-check, import-linter, unit tests
```

**Manual:** start the app (`make upd-local && uvicorn app.main.run:make_app --reload`), then via the real HTTP entrypoint:
1. `POST /api/v1/account/login/` with `{"identifier": "<existing username>", "password": "..."}` → 200 + cookie.
2. `POST /api/v1/account/login/` with `{"identifier": "<existing user's email>", "password": "..."}` → 200 + cookie.
3. `POST /api/v1/account/login/` with a too-short/malformed `identifier` → 400.
4. Sign up a brand-new user with a password shorter than 12 chars → 400 (new policy in effect).
