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

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Log in by username or email | user | to log in with either my username or my email in one `identifier` field | I can use whichever one I remember | `POST /api/v1/account/login/` with `{"identifier", "password"}` returns 200 and a session cookie for both<br>The email is matched case-insensitively<br>An unknown user and a wrong password both get 401 `Not authenticated.` |
| 2. A strong password policy | user | weak passwords rejected with a clear reason | my account is harder to guess | 12 to 128 characters, at least one letter, one digit and one special character from `!@#$%^&*()_+-=[]{}\|;:,.<>?`<br>Breaking a rule gives 400 naming that rule<br>Applies at sign-up, password change and the CLI's `create-user`/`set-user-password` |

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

---

## Human checks

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3), with copy-pasteable `curl` commands.

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`.
2. Start from a fresh, freshly seeded database (`make down` discards the old one), with the app on http://localhost:8000:
   ```shell
   make down
   make upd
   ```
   Re-run these to reset, because check 14 creates a user.
3. Each user gets their own cookie file in `/tmp` (`-c` saves it at login, `-b` sends it). A session lasts only 5 minutes without use, so every check that needs a session logs in at its own start. Run every command in the same terminal, top to bottom. Seeded accounts used below (from `SEED_USERS` in `scripts/seed_db.py`):
   - `jean-grey` / `Phoenix19864202!`, email `jean.grey@xmen.org`, a site ADMIN (checks 7 and 14 also use her to list which usernames exist)
   - `matt-murdock` / `Daredevil1!!`, email `matt.murdock@nelsonmurdock.com`
   - `luke-cage` / `PowerMan2024!`, email `luke.cage@harlemheroes.com`
4. Checks 9 to 14 sign up a new user, `clark-kent`. Only the password changes between them. Sign-up checks the password before it touches the database, so checks 9 to 13 fail on the password rule alone, whether or not `clark-kent` exists.

### Checks

1. **Log in by username: 200.**

   **Why:** `identifier` accepts a username. Anything that isn't a valid email is looked up as a username.
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
   ```
   Expect `200`, with `"username": "jean-grey"`.

2. **Log in by email: 200.**

   **Why:** the same `identifier` field accepts an email, so a user can log in with whichever one they remember. A valid email is tried first.
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/matt-murdock.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "matt.murdock@nelsonmurdock.com", "password": "Daredevil1!!"}'
   ```
   Expect `200`, with `"username": "matt-murdock"`.

3. **The email is matched case-insensitively: 200.**

   **Why:** emails are stored lowercased, and `Email` lowercases the identifier too, so a user who types capitals still matches.
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/luke-cage.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "Luke.Cage@HarlemHeroes.com", "password": "PowerMan2024!"}'
   ```
   Expect `200`, with `"username": "luke-cage"`.

4. **The session cookie works: 200.**

   **Why:** a login is only useful if the cookie it sets authenticates later requests. The session is keyed on the user's id, not on the identifier used to log in.

   Log in as `jean-grey`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
   ```
   Expect `200`. Then, with her cookie:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/jean-grey.cookies http://localhost:8000/api/v1/account/profile/
   ```
   Expect `200`, with `"email": "jean.grey@xmen.org"`.

5. **Logging in again while logged in: 403.**

   **Why:** a logged-in user can't log in again until they log out or the session expires. It's 403, not 401: the caller *is* authenticated, the action just isn't allowed.

   Log in as `jean-grey`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
   ```
   Expect `200`. Then log in again, this time sending her cookie:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
   ```
   Expect `403`, with `You are already authenticated. Consider logging out.`

6. **A wrong password: 401.**

   **Why:** a wrong password must not log anyone in. It still follows the password rules, so it gets as far as the lookup and fails there, rather than with a 400.
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "WrongPassword1!"}'
   ```
   Expect `401`, with `Not authenticated.`

7. **An unknown username or email: the same 401.**

   **Why:** an unknown account gets the same answer as check 6's wrong password, so a caller can't tell which accounts exist. That's also why it's 401 and not 404.

   **Prove** neither account exists. Log in as `jean-grey`, an admin, and list every username and email:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
   curl -s -b /tmp/jean-grey.cookies 'http://localhost:8000/api/v1/users/?limit=100' \
     | python3 -c 'import sys, json; print(sorted((u["username"], u["email"]) for u in json.load(sys.stdin)["users"]))'
   ```
   Expect `200`, then the 15 seeded users, with no `nobody-here` and no `nobody@example.com`. Then try both:
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "nobody@example.com", "password": "WrongPassword1!"}'
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "nobody-here", "password": "WrongPassword1!"}'
   ```
   Expect `401` both times, with `Not authenticated.`

8. **An identifier that is neither a valid email nor a valid username: 400.**

   **Why:** `abc` isn't an email, so it's read as a username, and usernames are 5 to 20 characters. It's rejected as bad input (400) before any lookup, so it can't reveal anything about accounts.
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "abc", "password": "WrongPassword1!"}'
   ```
   Expect `400`, with `Username must be between 5 and 20 characters.`

9. **Sign-up with a password under 12 characters: 400.**

   **Why:** the minimum is 12 characters, the NIST 800-63B floor. `Sh0rt!pass` is 10 characters and has a letter, digit and special character, so only the length rule fails.
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "clark-kent", "password": "Sh0rt!pass", "email": "clark.kent@dailyplanet.com", "phone_number": "0821000099"}'
   ```
   Expect `400`, with `Password must be at least 12 characters long.`

10. **Sign-up with a password over 128 characters: 400.**

    **Why:** an upper bound keeps arbitrarily long input from costing CPU when it's hashed. The shell builds a 132-character password that passes every other rule.
    ```shell
    PW=$(printf 'Aa1!%.0s' {1..33})
    curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
      -H 'Content-Type: application/json' \
      -d "{\"username\": \"clark-kent\", \"password\": \"$PW\", \"email\": \"clark.kent@dailyplanet.com\", \"phone_number\": \"0821000099\"}"
    ```
    Expect `400`, with `Password must be at most 128 characters long.`

11. **Sign-up with no letter: 400.**

    **Why:** the composition rule needs at least one letter, one digit and one special character, which rejects trivially weak patterns locally, with no outside service. `1234567890!@` has a digit and a special character but no letter.
    ```shell
    curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
      -H 'Content-Type: application/json' \
      -d '{"username": "clark-kent", "password": "1234567890!@", "email": "clark.kent@dailyplanet.com", "phone_number": "0821000099"}'
    ```
    Expect `400`, with `Password must contain at least one letter.`

12. **Sign-up with no digit: 400.**

    **Why:** the same composition rule as check 11. `NoDigitsHere!!` has letters and special characters but no digit.
    ```shell
    curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
      -H 'Content-Type: application/json' \
      -d '{"username": "clark-kent", "password": "NoDigitsHere!!", "email": "clark.kent@dailyplanet.com", "phone_number": "0821000099"}'
    ```
    Expect `400`, with `Password must contain at least one digit.`

13. **Sign-up with no special character: 400.**

    **Why:** the same composition rule as check 11. `NoSpecial12345` has letters and digits but none of the allowed special characters.
    ```shell
    curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
      -H 'Content-Type: application/json' \
      -d '{"username": "clark-kent", "password": "NoSpecial12345", "email": "clark.kent@dailyplanet.com", "phone_number": "0821000099"}'
    ```
    Expect `400`, with `Password must contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?).`

14. **Sign-up with a valid password: 200, then log in by email: 200.**

    **Why:** a password that meets every rule is accepted, and the new account can log in straight away by email.

    **Prove** `clark-kent` doesn't exist yet. Log in as `jean-grey`, an admin, and list every username:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
    curl -s -b /tmp/jean-grey.cookies 'http://localhost:8000/api/v1/users/?limit=100' \
      | python3 -c 'import sys, json; print(sorted(u["username"] for u in json.load(sys.stdin)["users"]))'
    ```
    Expect `200`, then the 15 seeded usernames, with no `clark-kent`. Then sign up:
    ```shell
    curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
      -H 'Content-Type: application/json' \
      -d '{"username": "clark-kent", "password": "ManOfSteel2024!", "email": "clark.kent@dailyplanet.com", "phone_number": "0821000099"}'
    ```
    Expect `200`, with `"username": "clark-kent"`. Then:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/clark-kent.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "clark.kent@dailyplanet.com", "password": "ManOfSteel2024!"}'
    ```
    Expect `200`.

15. **Changing to a weak new password: 400.**

    **Why:** the policy applies to password changes too, not only sign-up, so an account can't be weakened later. It's 400, a bad value, even though the current password is right.

    Log in as `clark-kent` (created in check 14):
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/clark-kent.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "clark-kent", "password": "ManOfSteel2024!"}'
    ```
    Expect `200`. Then try the weak new password:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/clark-kent.cookies -X PUT http://localhost:8000/api/v1/account/password/ \
      -H 'Content-Type: application/json' \
      -d '{"current_password": "ManOfSteel2024!", "new_password": "weakpass"}'
    ```
    Expect `400`, with `Password must be at least 12 characters long.` **Prove** the password didn't change, by logging in again with the old one (no cookie sent, so it isn't refused as already logged in):
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/clark-kent.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "clark-kent", "password": "ManOfSteel2024!"}'
    ```
    Expect `200`, with `"username": "clark-kent"`.
