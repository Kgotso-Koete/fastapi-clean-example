# Users: Update User Profile

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/update_user_profile.py`](../../../../src/app/inbound/http/users/update_user_profile.py) — HTTP router
    - [`src/app/core/commands/update_user_profile.py`](../../../../src/app/core/commands/update_user_profile.py) — the `UpdateUserProfile` command
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`, `CanManageSubordinate`
    - [`src/app/core/common/sentinels.py`](../../../../src/app/core/common/sentinels.py) — `OMITTED` and `apply_when_present()`
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — `UserNotFoundError`
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)
    - [`docs/plans/10-profile-editing.md`](../../../../docs/plans/10-profile-editing.md) — the design, its decisions and the human checks

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`PATCH /api/v1/users/{user_id}/profile/` lets an admin edit a **subordinate** user's `username`, `email`, `phone_number` and `description` — the admin counterpart of [Account: Update Own Profile](account-update-own-profile.md). It answers `200` with the updated profile. `UpdateUserProfile`'s own docstring:

- Open to admins; edits another user's profile.
- Admins can edit subordinate users only, as SetUserPassword.
- No password needed: the role hierarchy is the authorization.
- A partial update: a field left out stays as it is; null clears the description.
- Every value is validated before anything changes.

Structurally it's [Set User Password](users-set-user-password.md) with different fields: the same two authorization checks, the same `for_update=True` lock on the target, and the same `404` for an unknown id. An ADMIN edits a USER, a SUPER_ADMIN edits an ADMIN, and nobody edits their own role or above through it. A plain USER can't use it at all, not even on themselves; they use `/account/profile/`.

## Request flow

!!! figure-wide "PATCH /api/v1/users/{user_id}/profile/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as update_user_profile router
        participant Cmd as UpdateUserProfile.execute()
        participant Authz as authorize()
        participant Storage as UserTxStorage (port)
        participant Tx as Flusher / TransactionManager

        Client->>Router: PATCH /users/{user_id}/profile/ {fields to change}
        Router->>Cmd: execute(UpdateUserProfileRequest) (MISSING → OMITTED)
        Cmd->>Cmd: current_user = get_current_user()
        Cmd->>Authz: CanManageRole(subject=current_user, target_role=USER)
        alt not satisfied
            Authz-->>Client: 403 Forbidden
        else satisfied
            Cmd->>Cmd: apply_when_present() on each field
            alt a value fails validation
                Cmd-->>Client: 400 Bad Request (BusinessTypeError)
            else all valid
                Cmd->>Storage: get_by_id(user_id, for_update=True)
                alt user is None
                    Storage-->>Client: 404 Not Found
                else user found
                    Cmd->>Authz: CanManageSubordinate(subject=current_user, target=user)
                    alt not satisfied
                        Authz-->>Client: 403 Forbidden
                    else satisfied
                        Cmd->>Cmd: apply the sent fields, set updated_at
                        Cmd->>Tx: flush()
                        alt username/email/phone number taken
                            Tx-->>Client: 409 Conflict
                        else
                            Cmd->>Tx: commit()
                            Router-->>Client: 200 OK (updated profile)
                        end
                    end
                end
            end
        end
    ```

    > `403`, not `404`, for a target at or above the caller's role: admins can list every user, so the account's existence is no secret.

## No password, and its own response type

The target's password isn't asked for: the role hierarchy is the authorization, as for [Set User Password](users-set-user-password.md). An admin changing a USER's email is therefore an account takeover only an admin can do, which is what `CanManageSubordinate` is for.

The command returns its own `UpdateUserProfileResponse` (a `TypedDict` with the profile's fields), not the query side's `UserQm`, because import-linter's CQRS contract forbids a `core` command from importing a query model. [`UpdateOrganization`](../../../../src/app/core/commands/update_organization.py) does the same with its own response type.

## Where to go next

- [Account: Update Own Profile](account-update-own-profile.md) — the self-service counterpart, including how a `PATCH` tells "left out" from `null`.
- [Users: Set User Password](users-set-user-password.md) — the same authorization shape for a password reset.
- [Core Patterns → Authorization & RBAC](../core-patterns/authorization-rbac.md#where-authorize-actually-gets-called) — every command that uses these two checks.
