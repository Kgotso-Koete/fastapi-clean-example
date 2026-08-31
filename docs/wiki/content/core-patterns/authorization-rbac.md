# Authorization & RBAC (Role-Based Access Control)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/common/authorization/base.py`](../../../../src/app/core/common/authorization/base.py) — `Permission`/`PermissionContext` base abstractions
    - [`src/app/core/common/authorization/composite.py`](../../../../src/app/core/common/authorization/composite.py) — `AnyOf`, the OR-combinator
    - [`src/app/core/common/authorization/permissions.py`](../../../../src/app/core/common/authorization/permissions.py) — `CanManageSelf`, `CanManageSubordinate`, `CanManageRole`
    - [`src/app/core/common/authorization/role_hierarchy.py`](../../../../src/app/core/common/authorization/role_hierarchy.py) — `ROLE_HIERARCHY`
    - [`src/app/core/common/authorization/authorize.py`](../../../../src/app/core/common/authorization/authorize.py) — the `authorize()` entry point
    - [`src/app/core/common/authorization/current_user_service.py`](../../../../src/app/core/common/authorization/current_user_service.py) — `CurrentUserService`
    - [`src/app/core/common/authorization/ports.py`](../../../../src/app/core/common/authorization/ports.py) — `AuthzUserFinder`
    - [`src/app/core/common/authorization/exceptions.py`](../../../../src/app/core/common/authorization/exceptions.py) — `AuthorizationError`

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The idea in one sentence

Role-Based Access Control (RBAC) in this codebase isn't a library or a decorator — it's a handful of small classes in [`src/app/core/common/authorization/`](../../../../src/app/core/common/authorization/) that compose like building blocks: a `Permission` is anything that can answer "is this allowed?" against a `PermissionContext`, and `authorize()` is the one place that question actually gets asked and turned into a raised exception on "no." Everything else — `CanManageSelf`, `CanManageSubordinate`, `CanManageRole`, and the `ROLE_HIERARCHY` mapping they read from — is just a concrete `Permission` built on top of that shape.

!!! figure "The composable Permission shape"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph base["base.py"]
            ctx["PermissionContext<br/>(frozen dataclass)"]
            perm["Permission[PC]<br/>is_satisfied_by(context) -> bool"]
        end
        subgraph concrete["permissions.py"]
            self["CanManageSelf"]
            sub["CanManageSubordinate"]
            role["CanManageRole"]
        end
        subgraph combinator["composite.py"]
            anyof["AnyOf(*permissions)<br/>OR: any() is_satisfied_by"]
        end

        perm -->|reads a| ctx
        self -->|implements| perm
        sub -->|implements| perm
        role -->|implements| perm
        anyof -->|implements| perm
        anyof -.->|wraps zero or more| perm

        linkStyle default stroke-width:3px,stroke:#333333
        style base stroke-width:1px,stroke:#333333
        style concrete stroke-width:1px,stroke:#333333
        style combinator stroke-width:1px,stroke:#333333
    ```

    > Note what's *not* in that diagram: there is no `AllOf`/AND-combinator anywhere in this codebase today — `composite.py` defines only `AnyOf`. If a future use case needed "the caller must satisfy both permission A and permission B," nothing here provides that out of the box; it would have to be written as a new `Permission` subclass or a new combinator, following the same additive pattern `AnyOf` itself follows (see [Additive Building Blocks](#anyof-the-or-combinator-and-why-theres-no-allof) below).

## `Permission` and `PermissionContext`: the two-class foundation

[`base.py`](../../../../src/app/core/common/authorization/base.py):

```python
@dataclass(frozen=True, slots=True)
class PermissionContext:
    pass


class Permission[PC: PermissionContext](ABC):
    @abstractmethod
    def is_satisfied_by(self, context: PC) -> bool: ...
```

`PermissionContext` is an empty, frozen, `slots`-based dataclass — a base type with no fields of its own. Every real permission check in this codebase works against a *subclass* of it (`UserManagementContext`, `RoleManagementContext` below) that adds the specific fields that check needs. Because those subclasses are frozen dataclasses defined purely by the values they carry, they fit this wiki's definition of a **Value Object** (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md)) — a context is built fresh for one authorization check and thrown away, never mutated.

`Permission` is an ABC (Abstract Base Class) — a class that declares an abstract method (`is_satisfied_by`) and can't be instantiated directly, only subclassed. It's also generic: `Permission[PC: PermissionContext]` uses Python's built-in generic-class syntax to say "this class is parameterized by some type `PC`, and `PC` must be a `PermissionContext` or a subclass of it." `CanManageSelf` is a `Permission[UserManagementContext]`, so its `is_satisfied_by` only type-checks against a `UserManagementContext`, never a `RoleManagementContext` — the two families of checks can't be mixed up by accident, and `mypy` catches it if they are.

## `AnyOf`: the OR-combinator (and why there's no `AllOf`)

[`composite.py`](../../../../src/app/core/common/authorization/composite.py):

```python
class AnyOf[PC: PermissionContext](Permission[PC]):
    def __init__(self, *permissions: Permission[PC]) -> None:
        self._permissions = permissions

    def is_satisfied_by(self, context: PC) -> bool:
        return any(p.is_satisfied_by(context) for p in self._permissions)
```

`AnyOf` is itself a `Permission` — it satisfies the exact same interface it composes over, so it can wrap any mix of concrete permissions *or* another `AnyOf`, arbitrarily nested. Its logic is a plain `any()` over whatever `Permission`s it was constructed with: satisfied the moment one of them returns `True`. Per its own test suite ([`tests/unit/core/common/authorization/test_composite.py`](../../../../tests/unit/core/common/authorization/test_composite.py)), an `AnyOf()` constructed with zero permissions is *not* satisfied — `any()` over an empty sequence is `False`, so an empty `AnyOf` denies by default rather than vacuously allowing.

Grepping the codebase confirms `AnyOf` is not wired into any production command or query today — its only callers are its own unit tests. The same is true of `CanManageSelf` (below): defined and unit-tested, but not currently invoked from any real `core.commands`/`core.queries` class. Both exist as ready-to-use building blocks — e.g. a hypothetical "a user may change their own profile, or an admin may change it for them" rule would compose cleanly as `AnyOf(CanManageSelf(), CanManageSubordinate())` — but this codebase's actual use cases (below) only ever reach for `CanManageRole` and `CanManageSubordinate` directly, unwrapped. There is no `AllOf` counterpart anywhere in the source tree; if this codebase ever needs "permission A **and** permission B," that combinator doesn't exist yet and would have to be added.

## The concrete permissions and `ROLE_HIERARCHY`

[`permissions.py`](../../../../src/app/core/common/authorization/permissions.py):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class UserManagementContext(PermissionContext):
    subject: User
    target: User


class CanManageSelf(Permission[UserManagementContext]):
    def is_satisfied_by(self, context: UserManagementContext) -> bool:
        return context.subject == context.target


class CanManageSubordinate(Permission[UserManagementContext]):
    def __init__(self, role_hierarchy: Mapping[UserRole, set[UserRole]] = ROLE_HIERARCHY) -> None:
        self._role_hierarchy = role_hierarchy

    def is_satisfied_by(self, context: UserManagementContext) -> bool:
        allowed_roles = self._role_hierarchy.get(context.subject.role, set())
        return context.target.role in allowed_roles


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleManagementContext(PermissionContext):
    subject: User
    target_role: UserRole


class CanManageRole(Permission[RoleManagementContext]):
    def __init__(self, role_hierarchy: Mapping[UserRole, set[UserRole]] = ROLE_HIERARCHY) -> None:
        self._role_hierarchy = role_hierarchy

    def is_satisfied_by(self, context: RoleManagementContext) -> bool:
        allowed_roles = self._role_hierarchy.get(context.subject.role, set())
        return context.target_role in allowed_roles
```

`subject` and `target`/`target_role` are the two roles ever compared. `subject` is always the caller — a `User` **Entity** (see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for what "Entity" means in this codebase's DDD vocabulary) fetched by [`CurrentUserService`](#currentuserservice-producing-the-subject) below. There are two flavors of "target," matching the two contexts:

- `UserManagementContext` compares against an actual `target: User` — used when a specific existing user is already in hand (e.g. the user being deactivated).
- `RoleManagementContext` compares against a bare `target_role: UserRole` — used as a coarse, "can this caller act on *any* account of this role at all" pre-check, before a specific target user has even been fetched from storage.

`CanManageSelf` doesn't touch `ROLE_HIERARCHY` at all — it's a plain identity check, `subject == target`, relying on `User`'s own equality. `CanManageSubordinate` and `CanManageRole` share the identical lookup shape: both take an *injectable* `role_hierarchy` mapping, defaulting to the real `ROLE_HIERARCHY`, so a unit test can substitute a fake mapping without touching dependency injection — and both do the same thing, `self._role_hierarchy.get(subject.role, set())`, then check whether the target (a role, or a `User`'s `.role`) is in that set.

[`role_hierarchy.py`](../../../../src/app/core/common/authorization/role_hierarchy.py):

```python
ROLE_HIERARCHY: Final[Mapping[UserRole, set[UserRole]]] = {
    UserRole.SUPER_ADMIN: {UserRole.ADMIN, UserRole.USER},
    UserRole.ADMIN: {UserRole.USER},
    UserRole.USER: set(),
}
```

This is the entire "hierarchy": a flat `dict` from one `UserRole` to the *set* of roles it's allowed to manage. There's no tree structure and no code that walks parent/child links or computes a transitive closure at lookup time — `ROLE_HIERARCHY[UserRole.SUPER_ADMIN]` already lists both `ADMIN` and `USER` explicitly, rather than just `ADMIN` with something inferring `USER` transitively underneath it. That's a real, notable consequence: the "hierarchy" only behaves like one because whoever edits this map keeps it manually transitive. Adding a fourth role in between `ADMIN` and `USER` would require updating `SUPER_ADMIN`'s set by hand — nothing derives it automatically. `UserRole.USER` maps to an empty set, so a plain user can never manage anyone, including themselves through this mechanism (that's what `CanManageSelf` is for instead).

## `authorize()`: the enforcement choke point

[`authorize.py`](../../../../src/app/core/common/authorization/authorize.py):

```python
def authorize[PC: PermissionContext](
    permission: Permission[PC],
    *,
    context: PC,
) -> None:
    if not permission.is_satisfied_by(context):
        raise AuthorizationError
```

This function is the *only* place `is_satisfied_by()` gets called from a real use case — every `core.commands`/`core.queries` class that needs an authorization check calls `authorize(some_permission, context=...)` rather than calling `is_satisfied_by()` directly. That's a deliberate choke point: whatever `Permission` is passed in (a single concrete one, or an `AnyOf(...)` composition), the failure behavior is identical everywhere — a plain [`AuthorizationError`](../../../../src/app/core/common/authorization/exceptions.py):

```python
class AuthorizationError(BaseError):
    default_message: ClassVar[str] = "Not authorized."
```

`AuthorizationError` carries no extra context about *which* permission failed — by the time it's raised, the use case has already returned control to its caller, and any inbound HTTP router maps it straight to `403 Forbidden` via its `error_map` (e.g. [`src/app/inbound/http/users/grant_admin.py`](../../../../src/app/inbound/http/users/grant_admin.py)'s `AuthorizationError: status.HTTP_403_FORBIDDEN`).

!!! figure "authorize() call flow inside a use case"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        start(["use case's execute()"])
        cus["CurrentUserService.get_current_user()"]
        subgraph build["build the context"]
            ctx["e.g. RoleManagementContext(subject=current_user, target_role=...)"]
        end
        subgraph check["authorize()"]
            sat{"permission.is_satisfied_by(context)?"}
        end
        raise_["raise AuthorizationError"]
        cont(["execute() continues"])
        http["inbound router's error_map"]
        forbidden(["403 Forbidden"])

        start --> cus
        cus --> ctx
        ctx --> sat
        sat -->|False| raise_
        sat -->|True| cont
        raise_ --> http
        http --> forbidden

        linkStyle default stroke-width:3px,stroke:#333333
        style build stroke-width:1px,stroke:#333333
        style check stroke-width:1px,stroke:#333333
    ```

## `CurrentUserService`: producing the `subject`

Every `authorize()` call needs a `subject` — the caller — and that always comes from [`CurrentUserService.get_current_user()`](../../../../src/app/core/common/authorization/current_user_service.py):

```python
async def get_current_user(self, *, for_update: bool = False) -> User:
    current_user_id = await self._identity_provider.get_current_user_id()
    user = await self._authz_user_finder.get_by_id(current_user_id, for_update=for_update)
    if user is None or not user.is_active:
        logger.warning("%s ID: %s.", AUTHZ_NO_CURRENT_USER, current_user_id)
        await self._access_revoker.remove_all_user_access(current_user_id)
        raise AuthorizationError
    return user
```

`IdentityProvider` answers "who does the incoming request claim to be" (a `UserId`, resolved from a session by an `outbound` adapter — see [Ports and Adapters (Repository Pattern)](ports-and-adapters.md) for what a **port** is and how `core` never imports the concrete adapter behind it); `AuthzUserFinder`, declared in [`ports.py`](../../../../src/app/core/common/authorization/ports.py), is the narrower port this file adds on top of that — just enough to fetch a live `User` by id:

```python
class AuthzUserFinder(Protocol):
    @abstractmethod
    async def get_by_id(self, user_id: UserId, *, for_update: bool = False) -> User | None: ...
```

It's a `typing.Protocol`, the same structural-typing style every port in this codebase uses (see [Ports and Adapters (Repository Pattern)](ports-and-adapters.md#ports-are-protocols-not-abcs-abstract-base-classes-with-abstractmethod-requiring-inheritance) for why `Protocol` rather than an ABC is the convention here). If the id resolves to no user at all, or a user who's since been deactivated, `get_current_user()` doesn't just fail — it opportunistically calls `AccessRevoker.remove_all_user_access()` first, so a session pointing at a deleted/deactivated account gets cleaned up as a side effect of the very check that rejects it, before raising the same `AuthorizationError` every other failed check raises. Because this method re-reads the user fresh from storage on every call rather than caching it, a role change (e.g. from [Revoke Admin](../use-case-examples/users-revoke-admin.md)) takes effect on that user's very next request, with no separate cache-invalidation step needed.

## Where `authorize()` actually gets called

Grepping `src/app/core/commands/` and `src/app/core/queries/` for real call sites shows a consistent shape across every command that touches another user's account (`CreateUser`, `ActivateUser`, `DeactivateUser`, `GrantAdmin`, `RevokeAdmin`, `SetUserPassword`): a coarse `authorize(CanManageRole(), context=RoleManagementContext(subject=current_user, target_role=...))` check runs *before* the target user is even fetched from storage, and — for the five commands that then load a specific target — a second, precise `authorize(CanManageSubordinate(), context=UserManagementContext(subject=current_user, target=user))` check runs once that target is in hand. [`ListUsers`](../../../../src/app/core/queries/list_users.py) only performs the first, coarse check (`target_role=UserRole.USER`), since a paginated listing has no single target user to re-check against. [Users: Grant Admin](../use-case-examples/users-grant-admin.md) and [Users: Revoke Admin](../use-case-examples/users-revoke-admin.md) walk through this exact two-stage sequence for one concrete pair of endpoints, including why passing `target_role=UserRole.ADMIN` instead of `UserRole.USER` is what actually restricts those two commands to super admins only.

## Where to go next

- [Ports and Adapters (Repository Pattern)](ports-and-adapters.md) — the general port/`Protocol` pattern `AuthzUserFinder` and every other port in this codebase follow.
- [Users: Grant Admin](../use-case-examples/users-grant-admin.md) and [Users: Revoke Admin](../use-case-examples/users-revoke-admin.md) — `CanManageRole`/`CanManageSubordinate`/`ROLE_HIERARCHY` applied to one concrete pair of endpoints, end to end.
- [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) — the Entity/Value Object vocabulary `User`, `UserManagementContext`, and `RoleManagementContext` are instances of.
