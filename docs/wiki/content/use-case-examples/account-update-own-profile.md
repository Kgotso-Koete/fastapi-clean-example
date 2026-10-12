# Account: Update Own Profile

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/account/update_own_profile.py`](../../../../src/app/inbound/http/account/update_own_profile.py) — the route
    - [`src/app/outbound/auth_ctx/handlers/update_own_profile.py`](../../../../src/app/outbound/auth_ctx/handlers/update_own_profile.py) — the `UpdateOwnProfile` handler
    - [`src/app/core/common/sentinels.py`](../../../../src/app/core/common/sentinels.py) — `OMITTED`, `Omitted` and `apply_when_present()`, for "left out" vs `null`
    - [`src/app/inbound/missing.py`](../../../../src/app/inbound/missing.py) — `omit_if_missing()`, turning pydantic's `MISSING` into `OMITTED`
    - [`src/app/outbound/auth_ctx/exceptions.py`](../../../../src/app/outbound/auth_ctx/exceptions.py) — `ReAuthenticationError`
    - [`src/app/main/ioc/outbound.py`](../../../../src/app/main/ioc/outbound.py) — DI wiring (`AuthProvider`)
    - [`docs/plans/10-profile-editing.md`](../../../../docs/plans/10-profile-editing.md) — the design, its decisions and the human checks

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`PATCH /api/v1/account/profile/` lets any logged-in user edit their own `username`, `email`, `phone_number` and `description`. There's no user id in the URL: the handler edits whoever the session belongs to, so nobody can reach someone else's profile through it. It answers `200` with the updated profile, the same shape as `GET /api/v1/account/profile/`. `UpdateOwnProfile`'s own docstring:

- Open to any logged-in user; edits only the caller, never an id from the path.
- A partial update: a field left out stays as it is; null clears the description.
- Every value is validated before anything changes.
- Changing the email needs the current password, like ChangePassword.
- A username, email or phone number another account has is a 409.

It lives in `outbound/auth_ctx/handlers/`, beside [Change Password](account-change-password.md), not in `core/commands/`: like changing your password, changing your own login identifiers is a self-service credential operation, and it reuses `ChangePassword`'s `ReAuthenticationError`. The admin counterpart, [Users: Update User Profile](users-update-user-profile.md), is a `core` command like `SetUserPassword`.

## Partial updates: left out vs `null`

A `PATCH` has to tell three cases apart for the description: left out (keep it), `null` (clear it), and text (set it). Two sentinels carry "left out" through the layers:

- The route's request schema defaults every field to pydantic's `MISSING`. `omit_if_missing()` turns `MISSING` into core's `OMITTED` before the handler sees it, so the handler never depends on pydantic.
- The handler validates each field with `apply_when_present()`, which leaves `OMITTED` and `None` as they are and builds the value object otherwise.

[`update_own_profile.py`](../../../../src/app/outbound/auth_ctx/handlers/update_own_profile.py) — validate everything first, then re-authenticate a changed email:
```python
username = apply_when_present(Username, request.username)
email = apply_when_present(Email, request.email)
phone_number = apply_when_present(PhoneNumber, request.phone_number)
description = apply_when_present(Description, request.description)

if not isinstance(email, Omitted) and email != current_user.email:
    await self._reauthenticate(current_user, request.current_password)
```

Only `description` can be `null`: `username`, `email` and `phone_number` are typed `str | Omitted`, so a `null` for them is a `422` from the request schema.

## Request flow

!!! figure-wide "PATCH /api/v1/account/profile/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as update_own_profile route
        participant Handler as UpdateOwnProfile.execute()
        participant Svc as UserService
        participant Tx as Flusher / TransactionManager

        Client->>Router: PATCH /account/profile/ {fields to change}
        Router->>Handler: execute(UpdateOwnProfileRequest) (MISSING → OMITTED)
        Handler->>Handler: current_user = get_current_user(for_update=True)
        alt not logged in
            Handler-->>Client: 401 Unauthorized
        else logged in
            Handler->>Handler: apply_when_present() on each field
            alt a value fails validation
                Handler-->>Client: 400 Bad Request (BusinessTypeError)
            else all valid
                alt email changed
                    Handler->>Svc: is_password_valid(current_user, current_password)
                    alt missing or wrong
                        Handler-->>Client: 403 Forbidden ("Invalid password.")
                    end
                end
                Handler->>Handler: apply the sent fields, set updated_at
                Handler->>Tx: flush()
                alt username/email/phone number taken
                    Tx-->>Client: 409 Conflict
                else
                    Handler->>Tx: commit()
                    Handler-->>Router: UserQm
                    Router-->>Client: 200 OK (updated profile)
                end
            end
        end
    ```

    > Every value is validated before anything is applied, so an invalid field never leaves a half-applied update. A missing and a wrong current password are the same `403`, as `PUT /api/v1/account/password/` answers a wrong one. Re-sending the current email needs no password.

## Why changing email needs the current password

Email is a login identifier, and there's no email verification yet. Without the password check, anyone holding a stolen session could move the account to an address they control (OWASP: re-authenticate before changing a login identifier). Username and phone number changes need no password. Sessions stay valid after a change, because they're keyed on the user's id, not on username or email.

## Where to go next

- [Users: Update User Profile](users-update-user-profile.md) — the admin counterpart: editing a subordinate's profile, with no password.
- [Account: Change Password](account-change-password.md) — the other self-service credential change, and the source of `ReAuthenticationError`.
- [Data Models → Database Models](../data-models/database-models.md#nullable-value-objects-the-nullable-composite-recipe) — how the nullable `users.description` column maps onto `User.description`.
