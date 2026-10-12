# 10. Profile editing: user descriptions, and editing user profiles

> **Status: ready to start (plan 15 done and released as 0.18.0, 2026-10-09).** `docs/plans/15-upstream-autumn-2026.md` brought in the `Omitted` sentinel this plan's `PATCH` routes use (decided by the human maintainer, 2026-10-07), and two rules every new route now follows: a Swagger request-body example, and route tests that check the state after a refusal (Step 6 below). Private API (`/api/v1/...`, cookie auth) only; nothing here is exposed on the public API for writing (see "Why not the public API" below).
>
> **Moved out:** the organization half (an organization's mandatory description, the `Description` value object, `UpdateOrganization` and `PATCH /api/v1/organizations/{organization_id}/`) was built in `docs/plans/9-organizations.md`, Step 13, with its human checks there. This plan reuses that `Description` value object.

## Goal

One small, complete vertical slice that nearly every application needs: a user edits their own profile (username, email, phone number, and an optional description), and a platform admin edits another user's profile within the existing role hierarchy.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Describe myself | user | to add, change or clear a description on my own profile | others know who I am | `PATCH /api/v1/account/profile/` changes only the fields sent<br>1 to 1000 characters, line breaks allowed; longer or blank is 400<br>Sending `null` clears it; leaving it out keeps it |
| 2. Edit my identifiers | user | to change my username, email or phone number | my account stays current | A value another account already has is 409, and nothing changes<br>Changing email needs my current password in the same request<br>I only ever edit myself, never an id from the path |
| 3. Edit a subordinate | platform admin | to edit another user's profile | I can fix accounts I manage | `PATCH /api/v1/users/{user_id}/profile/` works for a role below mine<br>An ADMIN editing a SUPER_ADMIN or another ADMIN is 403<br>An unknown user is 404; no target password needed |
| 4. See descriptions | user, or platform admin | to see a description where the profile is shown | I know who someone is | `GET /api/v1/account/profile/` and `GET /api/v1/users/` include `description`, `null` when there is none |

## Reference implementations

- **apptension/saas-boilerplate** (https://github.com/apptension/saas-boilerplate):
  - `UpdateCurrentUserMutation` (`packages/backend/apps/users/schema.py`) always edits the caller's own profile, never a user id taken from the request. We copy that shape for self-editing.
  - It keeps profile data on a separate `UserProfile`; this codebase doesn't, for one field (decision 1). Its editable fields are `first_name`, `last_name`, `avatar` and `language`; email is read-only there, and it has **no description or bio field**. That part is this codebase's own design.
- **The original author's "Autumn 2026 Updates & Fixes"** (https://github.com/ivan-borovets/fastapi-clean-example/commit/5d68d52c9635c7da74d4d45ffb58493f267531aa): its `Omitted` sentinel (`core/common/sentinels.py`) and `omit_if_missing` (`inbound/missing.py`) tell "field left out" from "field sent as `null`" in a `PATCH`. Brought in by `docs/plans/15-upstream-autumn-2026.md`, Step 2, and used here for decision 3.
- **OWASP** (https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html): re-authenticate before changing an account's email. That's decision 2. OWASP also recommends notifying the old address; deferred, see "Deliberately out of scope".

## Decisions

1. **The description is a nullable column on `users`, held by `User`** (decided by the human maintainer, 2026-10-09, replacing the earlier separate `UserProfile` table: "Its really not worth creating a new table just for 1 field... this is my call, I made the trade off"). A conscious exception to the additive rule (`agents.md` 3.1) for the original author's `User` (`core/common/entities/user.py`), kept to the smallest change: one added constructor argument, `description: Description | None = None`, whose default leaves every existing caller (`UserService.create_user`, the test factories, the seed script) unchanged; one nullable `Text` column; a migration that only adds that column, with no backfill. The trade-off accepted: a later profile-only field (plan 12's image gallery) is decided on its own merits then.
2. **Changing email needs the current password** (decided earlier: option a), until email verification exists; then it becomes "verify the new address before switching". Email is a login identifier, and without this anyone holding a stolen session could move the account to an address they control. The admin path doesn't need the target's password: the role hierarchy authorizes it.
3. **Clearing a description: `null` clears it** (decided 2026-10-07). In a `PATCH`, `{"description": null}` clears it, a left-out field stays unchanged, and blank text is refused (`400`), as for organizations. One way to say "none", and the `Description` value object's rules stay the same everywhere.
4. **Descriptions are shown through the original author's `UserQm`** (decided 2026-10-07). `UserQm` gains `description: str | None`; `GetOwnProfile` and `ListUsers` fill it. This touches the original author's read model, one query and one adapter, flagged as such (`agents.md` 3.1):
   - `UserQm`: one added field.
   - **No default on it, and `LogIn` and `SignUp` fill it too** (2026-10-12). Step 3 gave the field a `None` default to keep existing `UserQm(...)` calls working until Step 5. Step 5 updated the read side but missed the original author's `LogIn` and `SignUp`, which also build a `UserQm`, and the default hid that from mypy: login answered `"description": null` for a user who had one. Human check 3's read-back caught it. Now `LogIn` passes the stored description, `SignUp` passes `None` (a new account has none), and the default is gone, so mypy rejects any `UserQm(...)` that leaves the field out. Pinned by `test_returns_200_with_the_users_description` in `tests/integration/with_infra/account/test_log_in.py`.
   - `GetOwnProfile`: one added line, `description=` from the `User` it already loads; no new dependency. It is bound in both `CoreProvider` and `PublicApiProvider`, so the public API's profile shows the description too, read-only; `tests/integration/with_infra/api_keys/test_get_profile.py` keeps the two JSON responses identical.
   - `SqlaUserReader`: selects one more column, `users.description`.

## Design

### Partial updates: left out vs `null`

- From plan 15, Step 2: `core/common/sentinels.py` (the original author's `Omitted` enum, its `OMITTED` member and `apply_when_present()`) and `inbound/missing.py` (`omit_if_missing()`, which turns pydantic's `MISSING` into `OMITTED`).
- A request dataclass field is `str | Omitted` for a field that can't be cleared (username, email, phone number), and `str | None | Omitted` for the description.

### `User.description`

- `User` gains `description: Description | None`, reusing the `Description` value object organizations use (1 to 1000 characters, line breaks allowed).
- **A plain attribute on `User`; `NULL` is handled in the mapping, with the original author's nullable-composite recipe** (decided by the human maintainer, 2026-10-11, "since that is the pattern established by the original author"). `self.description = description`, exactly like `Organization.description` and the original author's own `User` fields.
  - Why plain `composite(Description, ...)`, as `Organization.description` uses, isn't enough: that one is never `NULL`; a user's can be, and `composite()` calls `Description(None)` on load and crashes (`docs/plans/8-public-api-key-auth.md`, Step 3).
  - Why not a property and setter on the entity, as `ApiKey.revoked_at` and `OrganizationMembership.accepted_at` do: it costs one getter and one setter per optional field, so an entity with many optional fields (a booking or an order) would be flooded with them. The human maintainer's words: "the entity would be flooded with these getter setter nonsense".
  - **The recipe**, from the original author's upstream commit 5d68d52 (`src/app/outbound/persistence_sqla/mappings/composite/utc_datetime.py` and `registry.py`), which is SQLAlchemy maintainer Mike Bayer's documented approach for 2.0 (https://groups.google.com/g/sqlalchemy/c/nHz9z_P15qg/m/HWk8g8gGCAAJ):
    - `composite()` is given a **factory function** instead of the class: `nullable_description(value) -> Description | None`, which returns `None` for `NULL`, so loading is safe.
    - Given a function, SQLAlchemy can no longer read the value back out of a `Description` when saving, so a `patch()` attaches `__composite_values__` (returning `(self.value,)`) to `Description` at mapping time. `registry.py`'s `patch_composite()` runs every such patch.
    - Ported as written (`agents.md` 5.1), into `outbound/persistence_sqla/mappings/composite/`: `registry.py` with upstream's docstring, and `description.py`, the same shape as upstream's `utc_datetime.py`. Upstream's `utc_datetime.py` itself isn't taken: nothing here needs a nullable `UtcDatetime` composite yet.
    - The mapping: `"description": composite(nullable_description, users_table.c.description)`, over a plain nullable `Text` column, so Alembic writes an ordinary migration.
  - **Accepted costs:** the patch changes a `core` class at runtime from `outbound`, which import-linter and mypy can't see; and it must have run before any save. To make forgetting it impossible, `patch_composite()` runs where the mappings are set up (`map_tables()`), unless upstream calls it elsewhere, which is checked before GREEN and matched.
  - The four older nullable properties are converted later, in their own small plan (roadmap item); this plan doesn't touch them.
- No new ports: the commands load and save the `User` through the existing `UserTxStorage`, and the read side reads the column through the existing `CurrentUserService` and `SqlaUserReader`.

### Use cases

- **`UpdateOwnProfile`** (`outbound/auth_ctx/handlers/update_own_profile.py`): the caller edits only themselves, resolved through `CurrentUserService`, never a path id.
  - **Where it lives, aligned with the original author** (decided by the human maintainer, 2026-10-12): the original author keeps self-service operations on your own credentials in `outbound/auth_ctx/handlers/` (`SignUp`, `LogIn`, `ChangePassword`) and admin operations on other users in `core/commands/` (`CreateUser`, `SetUserPassword`). Changing your own username or email, login identifiers, behind your current password is `ChangePassword`'s kind of operation, so it sits beside it; `UpdateUserProfile` mirrors `SetUserPassword` in `core/commands/`. This replaces an earlier draft that put it in `core/commands/` and so needed two new errors duplicating `ReAuthenticationError`, which `core` can't import, plus its own response type.
  - Fields: `username`, `email`, `phone_number`, `description`, and `current_password`. Each value is checked by its existing value object (`Username`, `Email`, `PhoneNumber`, `Description`) before anything changes, so an invalid field never leaves a half-applied update.
  - Changing `email` to a different address needs the right `current_password`, checked with `UserService.is_password_valid()`. Missing or wrong are both the original author's `ReAuthenticationError` (`403`, "Invalid password."), as `ChangePassword` answers (decided by the human maintainer, 2026-10-12: one rule, no new error). A malformed one is `400`, from `RawPassword`, as in `ChangePassword`.
  - A username, email or phone number another account already has raises the existing `UsernameAlreadyExistsError`, `EmailAlreadyExistsError` or `PhoneNumberAlreadyExistsError` (`409`), from the existing database constraints, mapped by `SqlaFlusher`, the same path `SignUp` relies on. Nothing changes.
  - Any change, the description included, is made on the same `User` and sets its `updated_at`.
  - Returns the updated profile as the existing `UserQm`, as `SignUp` does.
- **`UpdateUserProfile`** (`core/commands/update_user_profile.py`): the same fields for another user, minus `current_password`.
  - Authorized exactly like `SetUserPassword`: `CanManageRole` (target role `USER`) for the caller, then, once the target is loaded, `CanManageSubordinate`. So an ADMIN edits a USER, a SUPER_ADMIN edits an ADMIN, and a plain USER can't use it at all (`403`). An unknown user is `UserNotFoundError` (`404`).

### Routes (private API)

- `PATCH /api/v1/account/profile/`: `UpdateOwnProfile`, in a new `inbound/http/account/update_own_profile.py`.
- `PATCH /api/v1/users/{user_id}/profile/`: `UpdateUserProfile`, in a new `inbound/http/users/update_user_profile.py`.

Both answer `200` with the updated profile. Errors, as the existing routers map them:
- `401` when not authenticated
- `403` for a role below what's required, or a missing or wrong current password on an email change
- `404` for an unknown user
- `400` when a value object's rules are broken
- `409` for a uniqueness clash
- `422` for a malformed request body

### Why not the public API

An API key is a narrow, per-user programmatic credential (`agents.md` 3.5). Letting a leaked key change the account's email or username, its login identifiers, would hand over the account itself. Reading the description through the public API's existing profile route is fine (decision 4); writing stays private.

### Deliberately out of scope

- **Notifying the old email address** after a change (OWASP recommends it): with email verification, a P0 roadmap item, which needs the same "send to an address" flow.
- **Revoking other sessions** on a username or email change: sessions are keyed on the user's id, so they stay valid by design; a password change is where sessions matter, and that already exists.

## Proposed changes (each step: test first, confirmed RED, then code, confirmed GREEN)

The `Omitted` sentinel this plan relies on is built first, in `docs/plans/15-upstream-autumn-2026.md`, Step 2.

1. **`User.description`:** a new `tests/unit/core/common/entities/test_user.py` (no description by default; built with one; set; clear), then the added argument and plain attribute on `User` (flagged, decision 1).
2. **Persistence:** an integration test that round-trips a user's description through Postgres (with one; `NULL`; changed; cleared), plus unit tests of the recipe itself in `tests/unit/outbound/persistence_sqla/mappings/test_composite_description.py` (`nullable_description` with `None` and with text; `__composite_values__` after `patch()`; `patch()` safe twice), then `mappings/composite/description.py` and `registry.py`, the `users.description` column and its mapping (flagged, decision 1), and the migration via `make migration msg="add description to users"`.
   - **Steps 1 and 2 done (2026-10-12):** `User.description` (4 unit tests); the recipe's `mappings/composite/description.py` and `registry.py` (4 unit tests), the `users.description` column and mapping, `patch_composite()` in `map_tables()`; migration `0014ed692f74` (`add description to users`: one nullable `String` column, nothing else). `make check` 519 passed; `make test-docker` passed with the 4 round-trip tests and the stairway.
3. **`UpdateOwnProfile`:** `tests/unit/outbound/auth_ctx/handlers/test_update_own_profile.py` (partial update; each field validated, nothing changed on refusal; `null` clears; blank `400`; a changed email needs the right current password, missing or wrong being `ReAuthenticationError`; same email needs none; uniqueness errors surface), then the handler, next to `ChangePassword`. Its response is `UserQm`, so this step also adds `description: str | None = None` to the original author's `UserQm` (flagged, decision 4); the default keeps every existing `UserQm(...)` call working until Step 5 fills it on the read side.
   - **Step 3 done (2026-10-12):** `outbound/auth_ctx/handlers/update_own_profile.py` (beside `ChangePassword`, reusing `ReAuthenticationError`, returning `UserQm`), and `UserQm.description` with its `None` default; 16 unit tests. `make check` 535 passed.
4. **`UpdateUserProfile`:** `tests/unit/core/commands/users/test_update_user_profile.py` (role hierarchy allow and deny; plain user denied; unknown user 404; no password for email), then the command.
   - **Step 4 done (2026-10-12):** `core/commands/update_user_profile.py` (the original author's `SetUserPassword` shape, returning its own `UpdateUserProfileResponse` since core commands may not import `UserQm`); 13 unit tests. `make check` 548 passed.
5. **Read side:** extend `tests/unit/core/queries/test_get_own_profile.py` and the `SqlaUserReader` integration test to expect `description`, then `UserQm`, `GetOwnProfile` and `SqlaUserReader` (flagged, decision 4).
   - **Step 5 done (2026-10-12):** `GetOwnProfile` and `SqlaUserReader` fill `UserQm.description` (the routes already returned `UserQm`, so no route change); one unit and two integration tests. `make check` 549 passed; `make test-docker` passed with the stairway.
6. **The routes:** `tests/integration/with_infra/account/test_update_own_profile.py` and `tests/integration/with_infra/users/test_update_user_profile.py` (status codes, state after refusal), then the two routes, their router registrations, and the DI bindings, appended (`agents.md` 3.1): `UpdateOwnProfile` in `AuthProvider` beside `ChangePassword`, `UpdateUserProfile` in `CoreProvider`.
   - **State after every refusal, not just the status** (the rule plan 15, Step 5, item 6 applied everywhere): after each `400`, `403`, `404` and `409`, the test re-reads the user and asserts nothing changed, including the other fields sent in the same request.
   - **A Swagger example on each route** (plan 15, Step 5, item 10): `tests/sanity/inbound/http/` fails `make check` for a JSON body with no example, so each route file declares an `<ROUTE>_EXAMPLES` constant passed as `Body(openapi_examples=...)`, with values that pass core's rules. Each route gets one example with every field (so the "complete example" check passes), plus `"clear_description": {"description": null}`, so Swagger shows that `null` clears. Own-profile examples are written for the seeded `peter-parker`; the admin route's for a USER that `miles-morales` (ADMIN) manages.
   - **The request model** keeps pydantic's `MISSING` default for left-out fields, turned into `OMITTED` by `omit_if_missing()` before the core request is built. Before writing it, confirm the generated schema still lets the sanity checker validate the examples (a field with a `MISSING` default may render differently from a plain `str | None`).
   - **One change to the original author's `omit_if_missing()`** (decided by the human maintainer, 2026-10-12): its parameter was `value: T`, which kept `MISSING` inside `T`, so mypy rejected every real call (a `str | MISSING` field can't become the core request's `str | Omitted`); upstream never called it outside a test, so it never surfaced there. It's now `value: T | MISSING`, which lets mypy solve `T` without `MISSING`; the body and behavior are unchanged, and upstream's two tests still pass. Rejected: a `# type: ignore` on each of the 8 calls (switches off checking exactly where the PATCH meaning matters), or dropping `MISSING` for pydantic's `model_fields_set` (leaves upstream's bridge unused).
   - **Step 6 done (2026-10-12):** the two routes, their router lines and DI bindings; 16 integration tests (9 own-profile, 7 admin). The `MISSING` defaults passed the Swagger example checks. `make check` 549 passed; `make test-docker` 842 passed, with the stairway.
7. **Seed data** (`scripts/seed_db.py`, no tests, `agents.md` 2.1): fixed ids for the seeded users (`e0000000-0000-4000-8000-0000000000NN`, where `NN` is the last two digits of the user's seeded phone number), and descriptions for `tony-stark` and `natasha-romanoff` only, so both states can be shown.
   - **Step 7 done (2026-10-12):** the id is built from the phone number in `_seed_one`, so the 15 `SeedUser(...)` lines are unchanged; the description is set after creation, like the super-admin role, so `UserService` is untouched.
8. **Docs and release:** the human checks below, wiki pages for the new use cases and the `users.description` column, `README.md` and roadmap sync, and a `CHANGELOG.md` entry (`agents.md` 1.4).
   - **Step 8 done (2026-10-12), 0.19.0:** every human check passed, run by the human maintainer. They caught the login answering `"description": null` (fixed test-first, decision 4) thanks to `agents.md` 1.3's rule that a check that changes data ends by reading it back (three checks lacked that read-back and got it), and added one rule there: commands show whole objects, never a few picked fields. `make check` 549 passed; `make test-docker` passed with the stairway.

## File summary

- **New:**
  - `src/app/outbound/auth_ctx/handlers/update_own_profile.py` (beside `ChangePassword`) and `src/app/core/commands/update_user_profile.py` (beside `SetUserPassword`); no new error classes
  - `outbound/persistence_sqla/mappings/composite/registry.py` and `description.py`, the original author's nullable-composite recipe; one migration (adds `users.description`)
  - `src/app/inbound/http/account/update_own_profile.py`, `src/app/inbound/http/users/update_user_profile.py`, each with its Swagger request-body examples
  - matching unit and integration test files
- **Changed:**
  - the original author's `User` and its `users` mapping (flagged, decision 1)
  - the original author's `UserQm`, `GetOwnProfile` and `SqlaUserReader` (flagged, decision 4)
  - the account and users routers (one line each), `AuthProvider` and `CoreProvider` bindings
  - `scripts/seed_db.py`
  - `CHANGELOG.md`, `README.md` checklist, roadmap, wiki

## Verification plan

- `make check` at every GREEN; `make test-docker` after every persistence or route step (`agents.md` 1.3).
- Architecture: `lint-imports` keeps `core.common` free of commands and queries, and `core` free of `outbound`; `mypy --strict`.
- The human checks below, against the seeded data.

## Human checks

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3). Every command's output is human-readable: JSON goes through `python3 -m json.tool`, and a command that shows its status code prints the code first, on its own line (`-w '%{stderr}%{http_code}\n'`), then the JSON.

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`. `OPEN_DASHBOARDS=` (empty) keeps `make upd` from opening browser tabs.
2. Start from a fresh, freshly seeded database. `make down` discards the old one:
   ```shell
   make down
   make upd
   ```
   Re-run these two commands to reset: the checks below change peter-parker's profile.
3. Each user gets their own cookie file in `/tmp` (for example `/tmp/peter-parker.cookies`). Every check logs in each user it acts as, because a session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN`); an expired cookie gets `401`. Run every command in the same terminal, top to bottom.
4. Each check runs its own read-only **Prove** command before the command under test, and a check that changes something ends by showing the change.

### Seeded data (from `scripts/seed_db.py`)

The users and passwords are the existing `SEED_USERS`, with fixed ids from Step 7:
- `peter-parker` (`SpideySense2024!`), id `e0000000-0000-4000-8000-000000000011`: platform USER, no description.
- `tony-stark` (`ImIronMan#3000`): platform USER, with a description.
- `miles-morales` (`WebSlingerHero1!`), id `e0000000-0000-4000-8000-000000000002`: platform ADMIN.
- `jean-grey`, id `e0000000-0000-4000-8000-000000000003`: platform ADMIN. Doesn't log in here.
- `ororo-munroe`, id `e0000000-0000-4000-8000-000000000001`: platform SUPER_ADMIN. Doesn't log in here.

### Who can do what

- **Any logged-in user:** edits their own profile only, at `/api/v1/account/profile/`, which takes no id. Changing their email also needs their current password.
- **Platform ADMIN:** also edits a USER's profile, at `/api/v1/users/{user_id}/profile/`, with no password needed.
- **Platform SUPER_ADMIN:** also edits an ADMIN's profile.
- Nobody edits someone of their own role or above through the admin route, and a plain USER can't use it at all.

### Editing your own profile

1. **Not logged in: 401.**

   **Why:** editing a profile needs a logged-in user. This command sends no cookie (there's no `-b`), so the server stops before it reads the body.

   **Acts on:** no one: without a cookie there is no caller.
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Hello"}' | python3 -m json.tool
   ```
   Expect `401`, with `"message": "Not authenticated."`.

2. **Add a description: 200.**

   **Why:** a user may describe themselves. Line breaks are allowed, because a description is prose. The route edits whoever the cookie belongs to; there's no user id in the URL, so nobody can edit someone else through it.

   **Acts on:** peter-parker's own profile, picked by his cookie.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`. **Prove** he has no description yet:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"username": "peter-parker"` and `"description": null`. Then, as `peter-parker`, set a two-line description:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Friendly neighborhood photographer.\nQueens, NY."}' | python3 -m json.tool
   ```
   Expect `200`, with `"description": "Friendly neighborhood photographer.\nQueens, NY."` (JSON shows the line break as `\n`). **Prove** it was stored:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect the same description.

3. **A partial update leaves the other fields alone: 200.**

   **Why:** `PATCH` changes only the fields sent. A client fixing one field must not wipe the others by leaving them out.

   **Acts on:** peter-parker's own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`. **Prove** the starting profile, and note its `username`, `email` and `description`:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Then, as `peter-parker`, change only the phone number:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"phone_number": "27821000099"}' | python3 -m json.tool
   ```
   Expect `200`, with `"phone_number": "27821000099"`, and `username`, `email` and `description` exactly as in the proof above. **Prove** it was stored:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect the same: the new phone number, and the other fields unchanged.

4. **`null` clears the description; blank text is refused: 200, then 400.**

   **Why:** decision 3: there is one way to say "no description", `null`, and it's never confused with leaving the field out. Blank text is refused (`400`, the `Description` value object's rule), the same as for organizations.

   **Acts on:** peter-parker's own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`. Give him a description, so there's something to clear:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Temporary."}' | python3 -m json.tool
   ```
   Expect `200`, with `"description": "Temporary."`. Then, as `peter-parker`, send only spaces:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "   "}' | python3 -m json.tool
   ```
   Expect `400`. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"description": "Temporary."` still. Then send `null`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": null}' | python3 -m json.tool
   ```
   Expect `200`, with `"description": null`. **Prove** it was stored:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"description": null`.

5. **A 1000-character description is accepted (`200`); a 1001-character one is refused (`400`).**

   **Why:** the `Description` value object allows 1 to 1000 characters. Over that it's `400`, not `422`: the body is well-formed JSON with a string where a string belongs; it's the domain rule that refuses it. Each **Prove** shows the whole profile, so you can see the description itself, then counts its characters, since 1000 `a`s can't be counted by eye.

   **Acts on:** peter-parker's own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`. Then, as `peter-parker`, send exactly 1000 `a`s:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d "{\"description\": \"$(printf 'a%.0s' $(seq 1 1000))\"}" | python3 -m json.tool
   ```
   Expect `200`, with a `description` of `a`s. **Prove** it was stored, and that it's exactly 1000 characters:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ \
     | python3 -c 'import sys, json; print("description length:", len(json.load(sys.stdin)["description"]))'
   ```
   Expect the profile with the `a`s as its `description`, then `description length: 1000`. Then send 1001:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d "{\"description\": \"$(printf 'a%.0s' $(seq 1 1001))\"}" | python3 -m json.tool
   ```
   Expect `400`, with a message about the description's length. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ \
     | python3 -c 'import sys, json; print("description length:", len(json.load(sys.stdin)["description"]))'
   ```
   Expect the same profile as before, then `description length: 1000` still.

6. **A username another account already has: 409.**

   **Why:** usernames are login identifiers, so they must be unique. It's `409`, not `400`: `tony-stark` is a valid username, it just clashes with an existing account. Nothing changes.

   **Acts on:** peter-parker's own profile, and the username of tony-stark's account.

   Log in as `tony-stark`, which **proves** the username `tony-stark` is taken, then as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}' | python3 -m json.tool
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200` with `"username": "tony-stark"`, then `200` with `"username": "peter-parker"`. Then, as `peter-parker`, try to take tony's username:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"username": "tony-stark"}' | python3 -m json.tool
   ```
   Expect `409`, with `"message": "Username already exists."`. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"username": "peter-parker"` still.

7. **Changing email without the right current password: 403, whether it's missing or wrong.**

   **Why:** decision 2: email is a login identifier and there's no email verification yet, so re-entering the password proves the person at the keyboard owns the account. Missing and wrong are the same refused re-authentication (`403`, "Invalid password.", as `PUT /api/v1/account/password/` answers): one rule, an email change needs your valid current password.

   **Acts on:** peter-parker's own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`, with `"email": "peter.parker@dailybugle.com"`: the **proof** of the starting email. Then, as `peter-parker`, change the email with no current password, then with a wrong one:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"email": "spidey@example.com"}' | python3 -m json.tool
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"email": "spidey@example.com", "current_password": "NotMyPassword123!"}' | python3 -m json.tool
   ```
   Expect `403` both times, with `"message": "Invalid password."`. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"email": "peter.parker@dailybugle.com"` still.

8. **Changing email with the current password: 200, and only the new email logs in.**

   **Why:** the allowed side of check 7. Logging in by email afterwards proves the change reached the login path, not just the profile.

   **Acts on:** peter-parker's own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`, with `"email": "peter.parker@dailybugle.com"`. Then, as `peter-parker`, change it with his current password:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"email": "spidey@example.com", "current_password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `200`, with `"email": "spidey@example.com"`. **Prove** the change reached login: log out, then log in with the old email, then the new one:
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/peter-parker.cookies -X DELETE http://localhost:8000/api/v1/account/logout/
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter.parker@dailybugle.com", "password": "SpideySense2024!"}' | python3 -m json.tool
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "spidey@example.com", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   Expect `204`; then `401` for the old email; then `200` with `"email": "spidey@example.com"`.

### Admin editing another user

9. **An ADMIN edits a USER's profile, with no target password: 200.**

   **Why:** a platform ADMIN manages accounts below their own role (`CanManageSubordinate`), the same rule `SetUserPassword` uses. The role hierarchy is the authorization, so the target's password isn't needed.

   **Acts on:** peter-parker's account (`e0000000-0000-4000-8000-000000000011`).

   Log in as `miles-morales`:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}' | python3 -m json.tool
   ```
   Expect `200`, with `"role": "admin"`. **Prove** that id is peter's, a plain USER, from the users list (his whole user object):
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
     | python3 -c 'import sys, json; print(json.dumps([u for u in json.load(sys.stdin)["users"] if u["username"] == "peter-parker"], indent=4))'
   ```
   Expect one object, with `"id": "e0000000-0000-4000-8000-000000000011"`, `"role": "user"` and his current `description`. Then, as `miles-morales`, edit peter's description:
   ```shell
   curl -s -w '%{stderr}%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
     http://localhost:8000/api/v1/users/e0000000-0000-4000-8000-000000000011/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Edited by an admin."}' | python3 -m json.tool
   ```
   Expect `200`, with `"username": "peter-parker"` and `"description": "Edited by an admin."`. **Prove** it was stored:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
     | python3 -c 'import sys, json; print(json.dumps([u for u in json.load(sys.stdin)["users"] if u["username"] == "peter-parker"], indent=4))'
   ```
   Expect peter's object with `"description": "Edited by an admin."` and every other field as in the proof above, except a newer `updated_at`.

10. **An ADMIN can't edit a SUPER_ADMIN, or another ADMIN: 403.**

    **Why:** an ADMIN manages only USERs. Otherwise an admin could change a super admin's email and take that account over, or two admins could take each other over. It's `403`, not `404`: admins can list every user, so the account's existence is no secret.

    **Acts on:** ororo-munroe's account (`e0000000-0000-4000-8000-000000000001`) and jean-grey's (`e0000000-0000-4000-8000-000000000003`).

    Log in as `miles-morales`:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}' | python3 -m json.tool
    ```
    Expect `200`, with `"role": "admin"`. **Prove** whose those ids are (their whole user objects):
    ```shell
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; print(json.dumps([u for u in json.load(sys.stdin)["users"] if u["username"] in ("ororo-munroe", "jean-grey")], indent=4))'
    ```
    Expect two objects: jean-grey with `"id": "e0000000-0000-4000-8000-000000000003"` and `"role": "admin"`, and ororo-munroe with `"id": "e0000000-0000-4000-8000-000000000001"` and `"role": "super_admin"`, each with `"description": null`. Then, as `miles-morales`, try to edit each:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
      http://localhost:8000/api/v1/users/e0000000-0000-4000-8000-000000000001/profile/ \
      -H 'Content-Type: application/json' -d '{"description": "Should not stick."}' | python3 -m json.tool
    curl -s -w '%{stderr}%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
      http://localhost:8000/api/v1/users/e0000000-0000-4000-8000-000000000003/profile/ \
      -H 'Content-Type: application/json' -d '{"description": "Should not stick."}' | python3 -m json.tool
    ```
    Expect `403` both times. **Prove** nothing changed:
    ```shell
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; print(json.dumps([u for u in json.load(sys.stdin)["users"] if u["username"] in ("ororo-munroe", "jean-grey")], indent=4))'
    ```
    Expect both objects exactly as in the proof above: `"description": null` and the same `updated_at`.

11. **An unknown user id: 404.**

    **Why:** there is no account to edit. `404`, as `SetUserPassword` answers for an unknown id.

    **Acts on:** `00000000-0000-4000-8000-000000000000`, an id no user has.

    Log in as `miles-morales`:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}' | python3 -m json.tool
    ```
    Expect `200`. **Prove** no user has that id, by counting matches in the users list:
    ```shell
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; print("users with that id:", sum(u["id"] == "00000000-0000-4000-8000-000000000000" for u in json.load(sys.stdin)["users"]))'
    ```
    Expect `users with that id: 0`. Then, as `miles-morales`, try to edit it:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
      http://localhost:8000/api/v1/users/00000000-0000-4000-8000-000000000000/profile/ \
      -H 'Content-Type: application/json' -d '{"description": "Nobody home."}' | python3 -m json.tool
    ```
    Expect `404`, with `"message": "User not found."`.

12. **A plain user can't use the admin route, not even on themselves: 403.**

    **Why:** a USER manages no one. Users edit themselves only through `/account/profile/`, which takes no id. `403`, not `404`: peter is logged in and the account exists; his role is just too low.

    **Acts on:** peter-parker's account (`e0000000-0000-4000-8000-000000000011`).

    Log in as `peter-parker`:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
    ```
    Expect `200`, with `"id": "e0000000-0000-4000-8000-000000000011"` and `"role": "user"`: the **proof**; note his description. Then, as `peter-parker`, try the admin route on himself:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH \
      http://localhost:8000/api/v1/users/e0000000-0000-4000-8000-000000000011/profile/ \
      -H 'Content-Type: application/json' -d '{"description": "Via the admin route."}' | python3 -m json.tool
    ```
    Expect `403`. **Prove** nothing changed:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
    ```
    Expect the same description as before, not `Via the admin route.`

### Seeing descriptions

13. **Descriptions show in the profile and the users list, `null` when there is none.**

    **Why:** decision 4: a description is shown wherever the profile is, and a user with none (a `NULL` `users.description`) reads as `null`, never an error.

    **Acts on:** tony-stark's and peter-parker's accounts.

    Log in as `tony-stark`, and as `miles-morales`:
    ```shell
    curl -s -w '%{stderr}%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}' | python3 -m json.tool
    curl -s -w '%{stderr}%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}' | python3 -m json.tool
    ```
    Expect `200` both times. Then tony's own profile, and the users list's descriptions as an admin sees them:
    ```shell
    curl -s -b /tmp/tony-stark.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' | python3 -m json.tool
    ```
    Expect tony's profile with his seeded `description`; then every user's whole object: tony's and natasha's with their seeded descriptions, peter's as whatever the checks above left, and the rest `"description": null`.

### Editing an organization

Moved: see `docs/plans/9-organizations.md`, "Step 13: describing and renaming an organization".
