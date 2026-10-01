# 10. Profile editing: descriptions, and editing users and organizations

> **Status: planned, not started.** Sequenced after `docs/plans/9-organizations.md` completes. Private API (`/api/v1/...`, cookie auth) only; nothing here is exposed on the public API (see "Why not the public API" below).

## Goal

Two small, complete vertical slices that nearly every application needs:

1. **User profile editing:** a user edits their own profile (username, email, phone number, description), and a platform admin edits another user's profile within the existing role hierarchy.
2. **Organization editing:** an organization's OWNER or ADMIN edits its name and description.

Both entities gain an optional free-text **description**.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Describe myself | user | to add, change or clear a description on my own profile | others know who I am | `PATCH /api/v1/account/profile/` changes only the fields sent<br>Up to 1000 characters, line breaks allowed; longer is 400<br>An empty description is stored as "no description" |
| 2. Edit my identifiers | user | to change my username, email or phone number | my account stays current | A value already taken by another account is 409, and nothing changes<br>Changing email needs my current password in the same request<br>I only ever edit myself, never an id from the path |
| 3. Edit a subordinate | platform admin | to edit another user's profile | I can fix accounts I manage | `PATCH /api/v1/users/{user_id}/profile/` works for a role below mine<br>An ADMIN editing a SUPER_ADMIN (or another ADMIN) is 403<br>An unknown user is 404; no target password needed |
| 4. Edit an organization | organization OWNER or ADMIN | to rename my organization and set its description | it's presented correctly to members | `PATCH /api/v1/organizations/{organization_id}/` changes only the fields sent<br>An invalid name is 400<br>The new name shows in `GET /api/v1/organizations/` |
| 5. Protect the organization | organization OWNER | MEMBERs and outsiders to be unable to edit my organization | only the people I trust with it can change it | A MEMBER gets 403<br>An outsider gets 404, so the organization's existence isn't revealed |

## Reference implementations

- **apptension/saas-boilerplate** (https://github.com/apptension/saas-boilerplate):
  - `UpdateCurrentUserMutation` (`packages/backend/apps/users/schema.py`) always edits the caller's own profile, never a user id taken from the request. We copy that shape for self-editing.
  - Its editable profile fields are `first_name`, `last_name`, `avatar` and `language`. Email is read-only there.
  - `UpdateTenantMutation` (`apps/multitenancy/schema.py`) lets OWNER or ADMIN edit the tenant's `name` and `billing_email`, gated by `IsTenantAdminAccess` plus `org.settings.edit`. We copy the OWNER/ADMIN rule.
  - apptension has **no description or bio field** on users or tenants. That part is this codebase's own design.
- The other two reference repos (https://github.com/philipokiokio/FastAPI_SAAS_Template, https://github.com/Avatarctic/clean-architecture-saas) have nothing relevant here.

## Design

### A `Description` value object (designed first)

Per `docs/plans/agents.md` 2.2, the value object comes before any entity field that holds it.

- Rules: `core/common/value_objects/description.py`, the same normalize-then-validate shape as `Email` and `OrganizationName`:
  - trimmed
  - 0 to 1000 characters after trimming
  - any printable Unicode, with line breaks allowed (it's prose, unlike `OrganizationName`)
  - control characters other than `\n`/`\t` rejected
- An empty description is stored as `NULL`, meaning "no description"; the entity field is `Description | None`.
- One value object serves both users and organizations. The rules are the same, so a second class would be duplication with no benefit.

### Where the user's description lives: a separate `UserProfile` (decided: option a)

`User` is the original author's entity (`core/common/entities/user.py`), and the additive rule (`agents.md` 3.1) says not to reach into it. There are two options:

- **(a) Recommended:** a new `UserProfile` entity and `user_profiles` table, one to one with `users` (`user_id` as primary key and foreign key, `ON DELETE CASCADE`), holding `description`. This leaves `User` and its mapping untouched, passes the "feature delete" test, and matches apptension, which also keeps profile data on a separate `UserProfile`. It is also the natural home for later profile-only data, such as the image array in plan 13.
- **(b)** A `description` column on `users` itself. This means one fewer table, but it edits the original author's entity, mapping and factories.

Organizations are this codebase's own code (plan 9), so `organizations.description` is simply a new nullable column.

### Use cases

- **`UpdateOwnProfile`** (command): the caller edits only themselves, resolved via `CurrentUserService` like apptension's `UpdateCurrentUserMutation`, never from a path id.
  - It is a partial update (`PATCH`): only the fields sent are changed.
  - The fields are `username`, `email`, `phone_number` and `description`, each validated by its existing value object.
  - A username, email or phone number already taken by another account raises the existing uniqueness errors (409). This reuses the checks sign-up already relies on.
- **`UpdateUserProfile`** (admin command): the same fields for another user.
  - Authorized by the existing `CanManageSubordinate` role hierarchy (`core/common/authorization/permissions.py`), so an ADMIN edits a USER and a SUPER_ADMIN edits an ADMIN, exactly as `SetUserPassword` and `GrantAdmin` already are. This reuses the code; it is not a new rule.
- **`UpdateOrganization`** (command): `name` and `description`, partial update.
  - It requires `CurrentOrganizationService.require_role(organization_id, OrganizationRole.ADMIN)`, so an OWNER or ADMIN may edit, as in apptension, and a non-member gets 404 as elsewhere in plan 9.
  - The name is validated by `OrganizationName`.
- **Queries:** `GetOwnProfile`, `ListUsers` and the organization queries gain `description` in their read models. `GetOwnProfile` is the original author's code, so the field is added to its read model only, with no logic change. This is flagged for review when that step is reached.

### Email changes (decided: option a)

Changing an email address without re-verifying it lets anyone with a stolen session move the account to an address they control. Email verification is already a P0 roadmap item that isn't built yet. Options:
- **(a) Recommended:** editing email requires the caller's current password in the same request, like `ChangePassword`, until email verification exists. Once it exists, it replaces this with "verify the new address before switching".
- **(b)** Leave email read-only, as apptension does, until email verification is built.
- **(c)** Allow it freely. Not recommended.

The admin path (`UpdateUserProfile`) doesn't need the target user's password; the role hierarchy already authorizes it.

### Routes (private API)

- `PATCH /api/v1/account/profile/`: `UpdateOwnProfile`
- `PATCH /api/v1/users/{user_id}/profile/`: `UpdateUserProfile`
- `PATCH /api/v1/organizations/{organization_id}/`: `UpdateOrganization`

Error mapping follows the existing routers:
- 401 when not authenticated
- 403 for a role below what's required
- 404 for an unknown user, or a non-member of the organization
- 400 when a value object's rules are broken
- 409 for a uniqueness clash
- 422 for a malformed request body

### Why not the public API

An API key is a narrow, per-user programmatic credential (`agents.md` 3.5). Letting a leaked key change the account's email or username, which are its login identifiers, would hand over the account itself. That is far more than anything else the key allows. Organization edits stay private for the same reason as every other organization write (scoped API keys come first).

## Proposed changes (each step: test first, confirmed RED, then code, confirmed GREEN)

1. **`Description` value object:** `tests/unit/core/common/value_objects/test_description.py`, then `core/common/value_objects/description.py`.
2. **Organization description:** extend the entity test, then the mapping round-trip test, then the entity and mapping changes, then `make migration`.
3. **`UserProfile`** (if option (a)): entity test, repository and reader integration tests, then the entity, mapping, adapter and migration. Existing users get a profile row lazily, the first time one is needed, so no backfill migration touches `users`.
4. **`UpdateOwnProfile`:** unit tests (partial update, each field validated, uniqueness 409, email rule per the decision above), then the command.
5. **`UpdateUserProfile`:** unit tests (role hierarchy allow and deny cases, unknown user 404), then the command.
6. **`UpdateOrganization`:** unit tests (OWNER and ADMIN allowed, MEMBER 403, non-member 404, invalid name 400), then the command.
7. **Read models:** query tests expecting `description`, then the reader changes.
8. **Routes and DI:** integration tests per route, then the routes and the `CoreProvider` bindings (appended, per `agents.md` 3.1).
9. **Seed data** (`scripts/seed_db.py`): descriptions on some superhero users and organizations, and leave others empty so both states can be demonstrated.
10. **Docs and release:** wiki pages for the new use cases, a `CHANGELOG.md` entry and a version bump (`agents.md` 1.4).

## File summary

- **New:**
  - `core/common/value_objects/description.py`
  - `core/common/entities/user_profile.py` (option a)
  - `core/commands/update_own_profile.py`, `update_user_profile.py`, `update_organization.py`
  - ports and adapters for `UserProfile` (option a)
  - three route modules
  - two migrations
  - matching unit and integration test files
- **Changed (additive):**
  - organization entity and mapping
  - `mappings/all.py`
  - `CoreProvider` bindings
  - router registration
  - read models and readers
  - `scripts/seed_db.py`
  - `CHANGELOG.md`, `README.md` checklist, roadmap

## Verification plan

- `make check` at every GREEN; `make test-docker` after every persistence or route step.
- Human-driven checks against the seeded data, via Swagger at `/docs`, Postman or `curl`:
  1. Log in as a seeded user, `PATCH /api/v1/account/profile/` with a new description, then `GET /api/v1/account/profile/`: the description is shown.
  2. Try to change your username to another seeded user's: 409, and nothing changes.
  3. As a seeded ADMIN, edit a USER's profile: 200. Try the same on a SUPER_ADMIN: 403.
  4. As a seeded organization ADMIN, rename the organization: the new name appears in `GET /api/v1/organizations/`. As a MEMBER, try the same: 403. As an outsider: 404.

## Human checks

(planned -- to run once this plan is implemented; commands follow the routes this plan defines)

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3). The users, passwords and organizations are the ones listed in `docs/plans/9-organizations.md`'s "Human checks" section and `scripts/seed_db.py`.

Details the plan leaves to implementation, so check the result against the rule rather than an exact value:
- the success status of a `PATCH` (the checks expect `200`, as the verification plan above does);
- what a `PATCH` returns in its body (so every check reads the result back with a `GET`);
- the name of the current-password field for an email change (the checks use `current_password`, the field `ChangePassword` already uses);
- the status for an email change with a missing or wrong current password (the plan says only that it's refused);
- the `description` field name in read models (the checks assume `description`, as Step 7 says).

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`.
2. Start from a fresh, freshly seeded database. `db_pg` has no named volume, so `make down` discards the old database:
   ```shell
   make down
   make upd
   ```
   Re-run these two commands to reset: the checks below change `peter-parker`'s profile and the Avengers' name and description.
3. Each user gets their own cookie file in `/tmp` (for example `/tmp/peter-parker.cookies`). Every check starts by logging in each user it acts as, because a session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN` in `src/app/main/config/settings.py`); an expired cookie gets `401`. A login answers `200` with the user's profile. Run every command in the same terminal, top to bottom.
4. Seeded user ids are generated, not fixed, so a check that needs one captures it into a shell variable (for example `$PETER_ID`) and prints it. Each check runs its own read-only **Prove** command before the command under test, and a check that changes something ends by showing the change.
5. The accounts (from `SEED_USERS` and `SEED_MEMBERSHIPS` in `scripts/seed_db.py`):
   - `peter-parker` (`SpideySense2024!`): platform USER; MEMBER of the Avengers.
   - `miles-morales` (`WebSlingerHero1!`): platform ADMIN.
   - `ororo-munroe`: platform SUPER_ADMIN. `jean-grey`: platform ADMIN. Neither logs in here.
   - `tony-stark` (`ImIronMan#3000`): OWNER of the Avengers (`a0000000-0000-4000-8000-000000000001`).
   - `natasha-romanoff` (`BlackWidow!!Red1`): ADMIN of the Avengers.
   - `wade-wilson` (`MaximumEffort2024!!!`): in no organization.

   Step 9 seeds descriptions on some users and organizations; no check below relies on which.

### Editing your own profile

1. **Not logged in: 401.**

   **Why:** editing a profile needs a logged-in user. This command sends no cookie (there's no `-b`), so the server stops before it reads the body.

   **Acts on:** no one: without a cookie there is no caller.
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Hello"}'
   ```
   Expect `401`.

2. **Add a description to your own profile: 200.**

   **Why:** a user may describe themselves. Line breaks are allowed because a description is prose, unlike an organization name. The route edits whoever the cookie belongs to; there is no user id in the URL, so nobody can edit someone else through it.

   **Acts on:** `peter-parker`'s own profile, picked by his cookie.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** the starting profile:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"username": "peter-parker"`, `"email": "peter.parker@dailybugle.com"`, `"phone_number": "27821000011"` and a `description` (`null`, or whatever Step 9 seeds for peter). Then, as `peter-parker`, set a two-line description:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Friendly neighborhood photographer.\nQueens, NY."}'
   ```
   Expect `200`. **Prove** the change:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"description": "Friendly neighborhood photographer.\nQueens, NY."` (JSON shows the line break as `\n`).

3. **A partial update leaves the other fields alone: 200.**

   **Why:** `PATCH` changes only the fields sent. A client fixing one field must not wipe the others by leaving them out.

   **Acts on:** `peter-parker`'s own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** the starting profile, and note its `username`, `email` and `description`:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Then, as `peter-parker`, change only the phone number:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"phone_number": "27821000099"}'
   ```
   Expect `200`. **Prove** the change:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"phone_number": "27821000099"`, and `username`, `email` and `description` exactly as in the proof above.

4. **An empty description clears it: 200.**

   **Why:** a description is trimmed, and an empty one is stored as "no description" (`null`). So there is one way to say "none", never both `""` and `null`.

   **Acts on:** `peter-parker`'s own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. First give him a description, so there is something to clear, and **prove** it's there:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "Temporary."}'
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `200`, then `"description": "Temporary."`. Then, as `peter-parker`, send only spaces:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"description": "   "}'
   ```
   Expect `200`. **Prove** the change:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"description": null`.

5. **Up to 1000 characters is fine: 200; one more is refused: 400.**

   **Why:** the `Description` value object allows 0 to 1000 characters. Over that it's 400, not 422: the body is well-formed JSON with a string where a string belongs, and it's the domain rule that refuses it. 422 is for a malformed body.

   **Acts on:** `peter-parker`'s own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. Then, as `peter-parker`, send exactly 1000 `a`s:
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d "{\"description\": \"$(printf 'a%.0s' $(seq 1 1000))\"}"
   ```
   Expect `200`. **Prove** it was stored, by counting the description's length:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ \
     | python3 -c 'import sys, json; print(len(json.load(sys.stdin)["description"]))'
   ```
   Expect `1000`. Then, as `peter-parker`, send 1001:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d "{\"description\": \"$(printf 'a%.0s' $(seq 1 1001))\"}"
   ```
   Expect `400`. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ \
     | python3 -c 'import sys, json; print(len(json.load(sys.stdin)["description"]))'
   ```
   Expect `1000` still.

6. **A username another account already has: 409.**

   **Why:** usernames are login identifiers, so they must be unique. It's 409, not 400: `tony-stark` is a valid username, it just clashes with an existing account. Nothing changes.

   **Acts on:** `peter-parker`'s own profile, and the username of `tony-stark`'s account.

   Log in as `tony-stark`. A `200` here **proves** the username `tony-stark` is taken:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
   ```
   Expect `200`, with `"username": "tony-stark"`. Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. Then, as `peter-parker`, try to take tony's username:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"username": "tony-stark"}'
   ```
   Expect `409`. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"username": "peter-parker"` still.

7. **Changing email without the right current password is refused.**

   **Why:** email can be a login identifier, and there's no email verification yet. Without this rule, anyone holding a stolen session could move the account to an address they control. Re-entering the password proves the person at the keyboard owns the account. The plan doesn't fix the status code: for a wrong password, expect what `ChangePassword` answers (`403`); for a missing one, any refusal (not `200`).

   **Acts on:** `peter-parker`'s own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** the starting email:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"email": "peter.parker@dailybugle.com"`. Then, as `peter-parker`, change the email with no current password, then with a wrong one:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"email": "spidey@example.com"}'
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"email": "spidey@example.com", "current_password": "NotMyPassword123!"}'
   ```
   Expect a refusal both times, not `200`. **Prove** nothing changed:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"email": "peter.parker@dailybugle.com"` still.

8. **Changing email with the current password: 200, and only the new email logs in.**

   **Why:** the allowed side of check 7. Logging in by email afterwards proves the change reached the login path, not just the profile.

   **Acts on:** `peter-parker`'s own profile.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`, with `"email": "peter.parker@dailybugle.com"`, the **proof** of the starting email. Then, as `peter-parker`, change it with his current password:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH http://localhost:8000/api/v1/account/profile/ \
     -H 'Content-Type: application/json' -d '{"email": "spidey@example.com", "current_password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** the change, by logging in with the old email, then the new one:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter.parker@dailybugle.com", "password": "SpideySense2024!"}'
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "spidey@example.com", "password": "SpideySense2024!"}'
   ```
   Expect `401` for the old email, then `200` with `"email": "spidey@example.com"`.

### Admin editing another user

9. **An ADMIN edits a USER's profile, with no target password: 200.**

   **Why:** a platform admin manages accounts below their own role (`CanManageSubordinate`: an ADMIN manages USERs), the same rule `SetUserPassword` uses. The role hierarchy is the authorization, so the target's password isn't needed.

   **Acts on:** `peter-parker`'s user id, saved in `$PETER_ID`.

   Log in as `miles-morales`, and as `peter-parker`, who checks the result:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200` both times, miles with `"role": "admin"`. Save peter's id from his own profile, and **prove** he's a plain USER:
   ```shell
   PETER_ID=$(curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ \
     | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')
   echo "$PETER_ID"
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect a UUID, then `"id"` equal to it and `"role": "user"`. Then, as `miles-morales`, edit peter's description:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
     "http://localhost:8000/api/v1/users/$PETER_ID/profile/" \
     -H 'Content-Type: application/json' -d '{"description": "Edited by an admin."}'
   ```
   Expect `200`. **Prove** the change, as `peter-parker`:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"description": "Edited by an admin."`.

10. **An ADMIN can't edit a SUPER_ADMIN, or another ADMIN: 403.**

    **Why:** an ADMIN manages only USERs. Otherwise an admin could change a super admin's email and take that account over, or two admins could take each other over. It's 403, not 404: admins can list every user, so the account's existence is no secret.

    **Acts on:** `ororo-munroe`'s user id, saved in `$ORORO_ID`, and `jean-grey`'s, saved in `$JEAN_ID`.

    Log in as `miles-morales`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
    ```
    Expect `200`, with `"role": "admin"`. Save both ids from the users list:
    ```shell
    ORORO_ID=$(curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; print(next(u["id"] for u in json.load(sys.stdin)["users"] if u["username"] == "ororo-munroe"))')
    JEAN_ID=$(curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; print(next(u["id"] for u in json.load(sys.stdin)["users"] if u["username"] == "jean-grey"))')
    echo "$ORORO_ID $JEAN_ID"
    ```
    Expect two UUIDs. **Prove** whose they are, and their roles and descriptions:
    ```shell
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; [print(u["username"], u["role"], u["id"], u["description"]) for u in json.load(sys.stdin)["users"] if u["username"] in ("ororo-munroe", "jean-grey")]'
    ```
    Expect `ororo-munroe super_admin` with `$ORORO_ID`, and `jean-grey admin` with `$JEAN_ID`; note each description. Then, as `miles-morales`, try to edit each:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
      "http://localhost:8000/api/v1/users/$ORORO_ID/profile/" \
      -H 'Content-Type: application/json' -d '{"description": "Should not stick."}'
    curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
      "http://localhost:8000/api/v1/users/$JEAN_ID/profile/" \
      -H 'Content-Type: application/json' -d '{"description": "Should not stick."}'
    ```
    Expect `403` both times. **Prove** nothing changed:
    ```shell
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; [print(u["username"], u["role"], u["id"], u["description"]) for u in json.load(sys.stdin)["users"] if u["username"] in ("ororo-munroe", "jean-grey")]'
    ```
    Expect the same descriptions as before, neither one `Should not stick.`

11. **An unknown user id: 404.**

    **Why:** there is no account to edit. 404, as `SetUserPassword` answers for an unknown id.

    **Acts on:** `00000000-0000-4000-8000-000000000000`, an id no user has.

    Log in as `miles-morales`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
    ```
    Expect `200`. **Prove** no user has that id, by counting matches in the users list:
    ```shell
    curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
      | python3 -c 'import sys, json; print(sum(u["id"] == "00000000-0000-4000-8000-000000000000" for u in json.load(sys.stdin)["users"]))'
    ```
    Expect `0`. Then, as `miles-morales`, try to edit it:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies -X PATCH \
      http://localhost:8000/api/v1/users/00000000-0000-4000-8000-000000000000/profile/ \
      -H 'Content-Type: application/json' -d '{"description": "Nobody home."}'
    ```
    Expect `404`.

12. **A plain user can't use the admin route, not even on themselves: 403.**

    **Why:** a USER manages no one (`ROLE_HIERARCHY` gives USER an empty set). Users edit themselves only through `/account/profile/`, which takes no id. 403, not 404: peter is logged in and the account exists, his role is just too low.

    **Acts on:** `peter-parker`'s user id, saved in `$PETER_ID`.

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. Save his id, and **prove** he's a plain USER:
    ```shell
    PETER_ID=$(curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ \
      | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')
    echo "$PETER_ID"
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
    ```
    Expect `"id"` equal to the printed UUID and `"role": "user"`; note the description. Then, as `peter-parker`, try the admin route on himself:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH \
      "http://localhost:8000/api/v1/users/$PETER_ID/profile/" \
      -H 'Content-Type: application/json' -d '{"description": "Via the admin route."}'
    ```
    Expect `403`. **Prove** nothing changed:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
    ```
    Expect the same description as before, not `Via the admin route.`

### Editing an organization

13. **An organization ADMIN renames it: 200, and the new name is listed.**

    **Why:** an organization's OWNER or ADMIN may edit it (`require_role(..., OrganizationRole.ADMIN)`); an ADMIN is the lowest role allowed.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

    Log in as `natasha-romanoff`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
    ```
    Expect `200`. **Prove** natasha is an ADMIN of the Avengers, by listing her organizations:
    ```shell
    curl -s -b /tmp/natasha-romanoff.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"id": "a0000000-0000-4000-8000-000000000001"` with `"name": "Avengers"` and `"role": "admin"`. Then, as `natasha-romanoff`, rename it:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/ \
      -H 'Content-Type: application/json' -d '{"name": "Avengers Assemble"}'
    ```
    Expect `200`. **Prove** the change:
    ```shell
    curl -s -b /tmp/natasha-romanoff.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect the same id with `"name": "Avengers Assemble"`.

14. **The OWNER sets a description: 200; an invalid name is refused: 400.**

    **Why:** an OWNER can do everything an ADMIN can. The name is checked by `OrganizationName`, which needs 1 to 100 characters, so an empty name is 400 (a domain rule), not 422 (a malformed body). The description is sent alone, so the name stays as it was.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

    Log in as `tony-stark`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
    ```
    Expect `200`. **Prove** tony is the Avengers' OWNER, and note its current `name`:
    ```shell
    curl -s -b /tmp/tony-stark.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"id": "a0000000-0000-4000-8000-000000000001"` with `"role": "owner"`. Then, as `tony-stark`, set a description, then try an empty name:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/ \
      -H 'Content-Type: application/json' -d '{"description": "Earth'"'"'s mightiest heroes."}'
    curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/ \
      -H 'Content-Type: application/json' -d '{"name": ""}'
    ```
    Expect `200`, then `400`. **Prove** the result:
    ```shell
    curl -s -b /tmp/tony-stark.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"description": "Earth's mightiest heroes."`, and the same `name` as in the proof above.

15. **A MEMBER can't edit the organization: 403.**

    **Why:** editing needs at least ADMIN. It's 403, not 404, because peter *is* a member: he may know the organization exists, he just can't change it.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. **Prove** peter is only a MEMBER, by listing his organizations, and note the Avengers' `name`:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"id": "a0000000-0000-4000-8000-000000000001"` with `"role": "member"`. Then, as `peter-parker`, try to rename it:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/ \
      -H 'Content-Type: application/json' -d '{"name": "Spider Squad"}'
    ```
    Expect `403`. **Prove** nothing changed:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect the same Avengers `name` as before, not `Spider Squad`.

16. **An outsider can't even see the organization: 404.**

    **Why:** to anyone without an accepted membership, the server answers as if the organization doesn't exist, as everywhere in plan 9. A 403 would confirm that it exists.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

    Log in as `wade-wilson`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
    ```
    Expect `200`. **Prove** wade belongs to no organization:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"organizations": []` and `"total": 0`. Then, as `wade-wilson`, try to rename the Avengers:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/ \
      -H 'Content-Type: application/json' -d '{"name": "Mercs For Money"}'
    ```
    Expect `404`, with `Organization not found.`
