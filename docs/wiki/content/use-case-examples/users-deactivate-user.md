# Users: Deactivate User

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/deactivate_user.py`](../../../../src/app/inbound/http/users/deactivate_user.py) — HTTP router
    - [`src/app/core/commands/deactivate_user.py`](../../../../src/app/core/commands/deactivate_user.py) — the `DeactivateUser` command
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.set_activation()`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`, `CanManageSubordinate`
    - [`src/app/core/common/ports/access_revoker.py`](../../../../src/app/core/common/ports/access_revoker.py) — `AccessRevoker` port
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — `UserNotFoundError`
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`DELETE /users/{user_id}/activation/` soft-deletes a user: it does not remove the row, it flips `is_active` to `false` and, unlike [Activate User](users-activate-user.md), also tears down every existing session that user holds. `DeactivateUser`'s own docstring:

- Open to admins.
- Soft-deletes existing user, making that user inactive.
- Also deletes user's sessions.
- Only super admins can deactivate other admins.
- Super admins cannot be soft-deleted.

## Request flow

!!! figure-wide "DELETE /users/{user_id}/activation/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as deactivate_user router
        participant Cmd as DeactivateUser.execute()
        participant Authz as authorize()
        participant Storage as UserTxStorage (port)
        participant Svc as UserService
        participant Tx as TransactionManager (port)
        participant Revoker as AccessRevoker (port)

        Client->>Router: DELETE /users/{user_id}/activation/
        Router->>Cmd: execute(DeactivateUserRequest(user_id))
        Cmd->>Cmd: current_user = get_current_user()
        Cmd->>Authz: CanManageRole(subject=current_user, target_role=USER)
        alt not satisfied
            Authz-->>Client: 403 Forbidden
        else satisfied
            Cmd->>Storage: get_by_id(user_id, for_update=True)
            alt user is None
                Storage-->>Client: 404 Not Found
            else user found
                Cmd->>Authz: CanManageSubordinate(subject=current_user, target=user)
                alt not satisfied
                    Authz-->>Client: 403 Forbidden
                else satisfied
                    Cmd->>Svc: set_activation(user, is_active=False)
                    alt user.role.is_system (super_admin)
                        Svc-->>Cmd: raises ActivationChangeNotPermittedError (unmapped, in practice unreachable — see below)
                    else state changed
                        Cmd->>Tx: commit()
                    end
                    Cmd->>Revoker: remove_all_user_access(user.id_)
                    Cmd-->>Router: None
                    Router-->>Client: 204 No Content
                end
            end
        end
    ```

    > The first two checks — `CanManageRole` then `CanManageSubordinate` — are identical to [Activate User](users-activate-user.md): a coarse role-level gate before the target is fetched, then a real per-target `ROLE_HIERARCHY` check once the target user's actual role is known (see that page for the full breakdown of why both run, and in that order).

## The "super admins cannot be soft-deleted" rule lives one layer deeper

Nothing in `DeactivateUser.execute()` itself special-cases the super admin role — that check isn't duplicated here as a third `authorize()` call. It's enforced inside [`UserService.set_activation()`](../../../../src/app/core/common/services/user.py) itself:

```python
def set_activation(self, user: User, *, now: UtcDatetime, is_active: bool) -> bool:
    if user.role.is_system:
        raise ActivationChangeNotPermittedError
    ...
```

`UserRole.is_system` is `True` only for `SUPER_ADMIN`. In practice this branch is unreachable via this endpoint's own authorization: `CanManageSubordinate` already requires the target's role to appear in the caller's `ROLE_HIERARCHY` entry, and no role's entry ever includes `SUPER_ADMIN` — so `CanManageSubordinate` itself would already have rejected a super-admin target before `set_activation()` is ever called. The service-level guard is a second, independent line of defense at the domain-invariant level, not the mechanism actually reached in the ordinary request path. Note also that this router's `error_map` (see the source file) doesn't map `ActivationChangeNotPermittedError` to any specific HTTP (HyperText Transfer Protocol) status at all — unlike the uniqueness errors on [Create User](users-create-user.md), which are deliberately mapped to `409`, this one was never expected to surface through the API (Application Programming Interface) in the first place, precisely because the authorization layer already forecloses it.

## Deactivation also revokes access — activation does not

The one real behavioral asymmetry with [Activate User](users-activate-user.md): after the commit, `DeactivateUser` unconditionally calls `AccessRevoker.remove_all_user_access(user.id_)`, tearing down every session the now-inactive user holds. This runs even if `set_activation()` returned `False` (the user was already inactive) — a deliberate "make sure of it" call rather than one conditioned on the state actually having changed, since a stray, not-yet-cleaned-up session on an already-inactive account is exactly the kind of drift this call exists to close. There is no equivalent call on activation, since re-activating a user never needs to *remove* access — it grants none by itself; the user still has to log in again to get a fresh session.

## Where to go next

- [Users: Activate User](users-activate-user.md) — the inverse operation, without session revocation.
- [Users: Revoke Admin](users-revoke-admin.md) — another command guarded by `CanManageRole` + `CanManageSubordinate` over the same `ROLE_HIERARCHY`.
- [Account: Log Out](account-log-out.md) — the other place in the codebase a session gets torn down via the same `AccessRevoker` port.
