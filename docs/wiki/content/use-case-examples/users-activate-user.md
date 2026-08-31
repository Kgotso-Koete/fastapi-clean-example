# Users: Activate User

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/inbound/http/users/activate_user.py`](../../../../src/app/inbound/http/users/activate_user.py) — HTTP router
    - [`src/app/core/commands/activate_user.py`](../../../../src/app/core/commands/activate_user.py) — the `ActivateUser` command
    - [`src/app/core/common/services/user.py`](../../../../src/app/core/common/services/user.py) — `UserService.set_activation()`
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageRole`, `CanManageSubordinate`
    - [`src/app/core/common/authorization/role_hierarchy.py`](../../../../src/app/core/common/authorization/role_hierarchy.py) — `ROLE_HIERARCHY`
    - [`src/app/core/commands/exceptions.py`](../../../../src/app/core/commands/exceptions.py) — `UserNotFoundError`
    - [`src/app/main/ioc/core.py`](../../../../src/app/main/ioc/core.py) — DI wiring (`CoreProvider`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this use case does

`PUT /users/{user_id}/activation/` restores a previously soft-deleted (deactivated) user, flipping `is_active` back to `true`. `ActivateUser`'s own docstring:

- Open to admins.
- Restores previously soft-deleted user.
- Only super admins can activate other admins.

This is the inverse of [Deactivate User](users-deactivate-user.md), and the two commands share almost the same shape — same two-stage authorization, same `UserService.set_activation()` call, opposite `is_active` value, and (unlike deactivation) no session revocation, since reactivating a user doesn't need to touch anyone's existing sessions.

## Request flow

!!! figure-wide "PUT /users/{user_id}/activation/ — request flow"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "16px"}, "sequence": {"useMaxWidth": false, "diagramMarginX": 30, "diagramMarginY": 20, "actorMargin": 90, "boxMargin": 12, "messageMargin": 45, "messageFontSize": 15, "actorFontSize": 15, "noteFontSize": 13, "wrap": true, "mirrorActors": false}}}%%
    sequenceDiagram
        participant Client
        participant Router as activate_user router
        participant Cmd as ActivateUser.execute()
        participant Authz as authorize()
        participant Storage as UserTxStorage (port)
        participant Svc as UserService
        participant Tx as TransactionManager (port)

        Client->>Router: PUT /users/{user_id}/activation/
        Router->>Cmd: execute(ActivateUserRequest(user_id))
        Cmd->>Cmd: current_user = get_current_user()
        Cmd->>Authz: CanManageRole(subject=current_user, target_role=USER)
        alt not satisfied
            Authz-->>Client: 403 Forbidden
        else satisfied
            Cmd->>Storage: get_by_id(user_id, for_update=True)
            alt user is None
                Storage-->>Client: 404 Not Found (UserNotFoundError)
            else user found
                Cmd->>Authz: CanManageSubordinate(subject=current_user, target=user)
                alt not satisfied
                    Authz-->>Client: 403 Forbidden
                else satisfied
                    Cmd->>Svc: set_activation(user, is_active=True)
                    alt state actually changed
                        Cmd->>Tx: commit()
                    end
                    Cmd-->>Router: None
                    Router-->>Client: 204 No Content
                end
            end
        end
    ```

    > Two distinct authorization checks run, in this order, and both must pass:
    >
    > 1. **`CanManageRole(subject=current_user, target_role=UserRole.USER)`** — a coarse, target-independent gate: this checks the caller is at least allowed to manage *some* `USER`-role account at all (true for any admin or super admin, since both have `USER` in their `ROLE_HIERARCHY` entry), before the target user is even looked up. This runs first specifically because looking the target up requires a database round-trip the code would rather skip for a caller who couldn't act on any user regardless of who the target turns out to be.
    > 2. **`CanManageSubordinate(subject=current_user, target=user)`** — the real, target-specific gate, once the actual target user (and therefore its real role) is known. This is what turns into "only super admins can activate other admins": an `admin` caller's allowed-roles set is `{USER}`, so a target user whose role is `admin` fails this check even though the coarse first check already passed.

## Why the row is locked before it's read

`user_tx_storage.get_by_id(user_id, for_update=True)` takes a row-level lock on the target user for the duration of the transaction. This matters because `UserService.set_activation()` performs a read-modify-write on `is_active` and `updated_at` — without the lock, two concurrent activation/deactivation requests against the same user could race between their own reads and writes. `set_activation()` also returns a `bool`: `False` if the user was already in the requested state (no-op, no commit needed), `True` if it actually changed something — the command only calls `TransactionManager.commit()` in the latter case, avoiding an empty commit for a call that changed nothing.

## Where to go next

- [Users: Deactivate User](users-deactivate-user.md) — the inverse operation, plus session revocation.
- [Users: Grant Admin](users-grant-admin.md) — the same `CanManageRole` + `CanManageSubordinate` two-stage authorization pattern, applied to role changes instead of activation state.
- [Adding a New REST Endpoint](adding-a-rest-endpoint.md) — the generic router-wiring template this endpoint follows.
