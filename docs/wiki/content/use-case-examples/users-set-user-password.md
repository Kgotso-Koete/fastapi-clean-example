# Users: Set User Password

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/set_user_password.py`](../../../../src/app/inbound/http/users/set_user_password.py) — HTTP router
    - [`src/app/core/commands/set_user_password.py`](../../../../src/app/core/commands/set_user_password.py) — the `SetUserPassword` command
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.change_password()`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`, `CanManageSubordinate`
    - [`src/app/core/common/value_objects/raw_password.py`](../../../../src/app/core/common/value_objects/raw_password.py) — `RawPassword` value object
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — `UserNotFoundError`
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`PUT /users/{user_id}/password/` lets an admin set a **subordinate** user's password directly — an administrative password reset, distinct from [Account: Change Password](account-change-password.md), where a logged-in user changes their own password. `SetUserPassword`'s own docstring:

- Open to admins.
- Admins can set passwords of subordinate users.

Structurally this command is closest to [Activate User](users-activate-user.md)/[Deactivate User](users-deactivate-user.md): it authorizes with `target_role=UserRole.USER` on the coarse check (any admin may act on some `USER`-role account), and locks the target row with `for_update=True` before mutating it.

## Request flow

!!! figure-wide "PUT /users/{user_id}/password/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as set_user_password router
        participant Cmd as SetUserPassword.execute()
        participant Authz as authorize()
        participant Storage as UserTxStorage (port)
        participant Svc as UserService
        participant Tx as TransactionManager (port)

        Client->>Router: PUT /users/{user_id}/password/ {password}
        Router->>Cmd: execute(SetUserPasswordRequest(user_id, password))
        Cmd->>Cmd: current_user = get_current_user()
        Cmd->>Authz: CanManageRole(subject=current_user, target_role=USER)
        alt not satisfied
            Authz-->>Client: 403 Forbidden
        else satisfied
            Cmd->>Cmd: password = RawPassword(request.password)
            alt password fails validation
                Cmd-->>Client: 400 Bad Request (BusinessTypeError)
            else
                Cmd->>Storage: get_by_id(user_id, for_update=True)
                alt user is None
                    Storage-->>Client: 404 Not Found
                else user found
                    Cmd->>Authz: CanManageSubordinate(subject=current_user, target=user)
                    alt not satisfied
                        Authz-->>Client: 403 Forbidden
                    else satisfied
                        Cmd->>Svc: change_password(user, password)
                        Cmd->>Tx: commit()
                        Cmd-->>Router: None
                        Router-->>Client: 204 No Content
                    end
                end
            end
        end
    ```

    > The router wraps the raw `password` field in a small Pydantic schema (`SetUserPasswordRequestSchema`) purely so Swagger UI renders a proper request-body shape — the class's own docstring says as much ("Using Pydantic model here is generally unnecessary. It's only implemented to render specific Swagger UI."). The command itself takes a plain dataclass (`SetUserPasswordRequest`) with a bare `str` password field; validation of the password's actual shape (length, character rules, etc.) happens when the command constructs `RawPassword(request.password)` — a **Value Object** (a Domain-Driven Design object defined purely by its value, per [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md#what-clean-architecture-and-domain-driven-design-actually-are)) that raises `BusinessTypeError` if construction fails, mapped by the router to `400 Bad Request`.

## No idempotency short-circuit — and no session revocation

Unlike [Activate User](users-activate-user.md)/[Deactivate User](users-deactivate-user.md)/[Grant Admin](users-grant-admin.md)/[Revoke Admin](users-revoke-admin.md), `UserService.change_password()` returns `None`, not a `bool` — there is no "was this actually a change" check to skip the commit on. Every successful call re-hashes the given password and unconditionally updates `password_hash` and `updated_at`, then `SetUserPassword.execute()` always calls `TransactionManager.commit()`. This makes sense for a password: unlike a role or an activation flag, there's no cheap, safe way to tell whether a new raw password happens to match the old one without re-deriving the hash anyway — so there's nothing to gain by trying to special-case a no-op here.

Also worth being explicit about: this command does **not** revoke the target user's existing sessions after changing their password, in contrast to [Deactivate User](users-deactivate-user.md)'s unconditional `AccessRevoker.remove_all_user_access()` call. `SetUserPassword` has no `AccessRevoker` dependency at all — an admin-initiated password reset leaves any session the user is already holding valid until it expires or they log out on their own.

## Where to go next

- [Account: Change Password](account-change-password.md) — the self-service counterpart: a user changing their own password, rather than an admin resetting someone else's.
- [Users: Activate User](users-activate-user.md) — the same `CanManageRole(target_role=USER)` + `CanManageSubordinate` authorization shape, with a state-change idempotency check this command doesn't have.
- [Users: Deactivate User](users-deactivate-user.md) — contrast with a command that does revoke sessions as part of the same operation.
