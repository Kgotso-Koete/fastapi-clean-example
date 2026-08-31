# Users: Grant Admin

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/grant_admin.py`](../../../../src/app/inbound/http/users/grant_admin.py) — HTTP router
    - [`src/app/core/commands/grant_admin.py`](../../../../src/app/core/commands/grant_admin.py) — the `GrantAdmin` command
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.set_role()`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`, `CanManageSubordinate`
    - [`src/app/core/common/authorization/role_hierarchy.py`](../../../../src/app/core/common/authorization/role_hierarchy.py) — `ROLE_HIERARCHY`
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — `UserNotFoundError`
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`PUT /users/{user_id}/roles/admin/` promotes an existing `user`-role account to `admin`. `GrantAdmin`'s own docstring:

- Open to super admins.
- Grants admin rights to specified user.
- Super admin rights cannot be changed.

Note the narrower "open to" line compared to [Create User](users-create-user.md), [Activate User](users-activate-user.md), or [Deactivate User](users-deactivate-user.md) — those are "open to admins"; this one is "open to super admins" only. That difference falls straight out of the same shared `ROLE_HIERARCHY` mechanism, not a separate rule: this command authorizes against `target_role=UserRole.ADMIN`, and `ROLE_HIERARCHY` gives only `SUPER_ADMIN` the `ADMIN` role in its allowed set (`ADMIN`'s own set is just `{USER}`).

## Request flow

!!! figure-wide "PUT /users/{user_id}/roles/admin/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as grant_admin router
        participant Cmd as GrantAdmin.execute()
        participant Authz as authorize()
        participant Storage as UserTxStorage (port)
        participant Svc as UserService
        participant Tx as TransactionManager (port)

        Client->>Router: PUT /users/{user_id}/roles/admin/
        Router->>Cmd: execute(GrantAdminRequest(user_id))
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
                    Cmd->>Svc: set_role(user, is_admin=True)
                    alt role actually changed
                        Cmd->>Tx: commit()
                    end
                    Cmd-->>Router: None
                    Router-->>Client: 204 No Content
                end
            end
        end
    ```

## Why the target_role is ADMIN here, but USER on the other commands

This is the one line in `GrantAdmin.execute()` that differs structurally from [Activate User](users-activate-user.md)/[Deactivate User](users-deactivate-user.md)/[Set User Password](users-set-user-password.md): those pass `target_role=UserRole.USER` to the coarse `CanManageRole` check, because operating on *some* `USER`-role account is the minimum bar any admin clears. `GrantAdmin` (and its inverse, [Revoke Admin](users-revoke-admin.md)) pass `target_role=UserRole.ADMIN` instead, because the operation being authorized — handing out or taking away admin rights — is itself an admin-role-level action, not a user-role-level one. Only a `super_admin`'s `ROLE_HIERARCHY` entry contains `ADMIN`, so this first check alone already excludes plain admins from calling this endpoint at all, before any target user is even fetched.

!!! figure "Role-authorization comparison across the Users use cases"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph target_user["target_role = USER"]
            activate["Activate/Deactivate User"]
            setpw["Set User Password"]
        end
        subgraph target_admin["target_role = ADMIN"]
            grant["Grant Admin"]
            revoke["Revoke Admin"]
        end
        target_user -->|passes for any admin or super_admin| ok1(["caller may proceed to CanManageSubordinate"])
        target_admin -->|passes for super_admin only| ok2(["caller may proceed to CanManageSubordinate"])

        linkStyle default stroke-width:3px,stroke:#333333
        style target_user stroke-width:1px,stroke:#333333
        style target_admin stroke-width:1px,stroke:#333333
    ```

    The coarse `CanManageRole` check's `target_role` argument is what actually decides which caller roles can reach the second, per-target `CanManageSubordinate` check at all — `USER` lets any admin through, `ADMIN` lets only a super admin through, before either check has even looked at who the specific target user is.

Once past that first gate, the second check — `CanManageSubordinate(subject=current_user, target=user)` — is identical in shape to every other command in this section: it re-checks `ROLE_HIERARCHY` against the *actual* target user's current role. Since `ROLE_HIERARCHY` never grants anyone permission over a `SUPER_ADMIN` target, a super admin's own rights can never be granted or revoked through this endpoint — matching the docstring's "Super admin rights cannot be changed" line. (As with [Deactivate User](users-deactivate-user.md), `UserService.set_role()` also carries its own `user.role.is_system` guard, raising `RoleChangeNotPermittedError` if it's ever reached — but `CanManageSubordinate` already makes that path unreachable through this HTTP (HyperText Transfer Protocol) endpoint, and the router's `error_map` doesn't map that exception to a specific status either.)

`UserService.set_role()` itself returns `False` (no commit) if the user is already an admin — granting admin rights to an existing admin is a no-op, not an error.

## Where to go next

- [Users: Revoke Admin](users-revoke-admin.md) — the inverse operation, same authorization shape.
- [Users: Create User](users-create-user.md) — the same `ROLE_HIERARCHY`/`CanManageRole` mechanism applied at account-creation time instead of to an existing user.
- [Users: Activate User](users-activate-user.md) — contrast with a command that authorizes against `target_role=USER`.
