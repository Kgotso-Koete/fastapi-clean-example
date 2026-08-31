# Users: Revoke Admin

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/revoke_admin.py`](../../../../src/app/inbound/http/users/revoke_admin.py) — HTTP router
    - [`src/app/core/commands/revoke_admin.py`](../../../../src/app/core/commands/revoke_admin.py) — the `RevokeAdmin` command
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.set_role()`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`, `CanManageSubordinate`
    - [`src/app/core/common/authorization/role_hierarchy.py`](../../../../src/app/core/common/authorization/role_hierarchy.py) — `ROLE_HIERARCHY`
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — `UserNotFoundError`
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`DELETE /users/{user_id}/roles/admin/` demotes an existing `admin`-role account back to `user`. `RevokeAdmin`'s own docstring:

- Open to super admins.
- Revokes admin rights from specified user.
- Super admin rights cannot be changed

`RevokeAdmin` is [Grant Admin](users-grant-admin.md)'s exact structural mirror: same **interactor** shape (a use-case class: one `execute()` method implementing a single application action), same two-stage authorization, same `UserService.set_role()` call with `is_admin=False` instead of `True`. Everything on that page about *why* `target_role=ADMIN` gates this to super admins only applies here identically — this page focuses on what's different about the revoke direction specifically.

## Request flow

!!! figure-wide "DELETE /users/{user_id}/roles/admin/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as revoke_admin router
        participant Cmd as RevokeAdmin.execute()
        participant Authz as authorize()
        participant Storage as UserTxStorage (port)
        participant Svc as UserService
        participant Tx as TransactionManager (port)

        Client->>Router: DELETE /users/{user_id}/roles/admin/
        Router->>Cmd: execute(RevokeAdminRequest(user_id))
        Cmd->>Cmd: current_user = get_current_user()
        Cmd->>Authz: CanManageRole(subject=current_user, target_role=ADMIN)
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
                    Cmd->>Svc: set_role(user, is_admin=False)
                    alt role actually changed
                        Cmd->>Tx: commit()
                    end
                    Cmd-->>Router: None
                    Router-->>Client: 204 No Content
                end
            end
        end
    ```

## What "revoking" actually does — and doesn't do

`UserService.set_role(user, is_admin=False)` sets `user.role = UserRole.USER` and stamps `updated_at`. It returns `False` (no commit) if the target was already a plain `user` — demoting a non-admin is a no-op, the same "idempotent, not an error" treatment [Grant Admin](users-grant-admin.md) gives to re-granting an existing admin.

One thing worth being explicit about: **revoking admin rights does not, by itself, revoke that user's existing sessions**, unlike [Deactivate User](users-deactivate-user.md), which unconditionally calls `AccessRevoker.remove_all_user_access()` after soft-deleting a user. `RevokeAdmin` has no `AccessRevoker` dependency in its constructor at all — a demoted admin who is still `is_active` keeps whatever session they were already holding; their *role* changes, not their *session's validity*. Any authorization check made against them afterward (via `CurrentUserService.get_current_user()`) re-reads their role fresh from storage each time, so the demotion still takes effect on their very next privileged action — it just isn't accompanied by a forced logout.

Because `CanManageSubordinate`'s `ROLE_HIERARCHY` lookup never grants any role authority over `SUPER_ADMIN`, a super admin's role can never be revoked through this endpoint — the "super admin rights cannot be changed" line from the docstring, enforced the same way as on [Grant Admin](users-grant-admin.md): by the authorization layer making the target unreachable, with `UserService.set_role()`'s own `RoleChangeNotPermittedError` guard as an unreachable-in-practice second line of defense (also unmapped in this router's `error_map`, for the same reason).

## Where to go next

- [Users: Grant Admin](users-grant-admin.md) — the inverse operation; the full breakdown of why `target_role=ADMIN` restricts this to super admins.
- [Users: Deactivate User](users-deactivate-user.md) — contrast with a command that *does* revoke sessions as part of the same operation.
- [Users: List Users](users-list-users.md) — how to see the resulting role/`is_active` state across all users after granting or revoking.
