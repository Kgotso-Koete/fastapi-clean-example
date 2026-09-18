# Organizations: an Additive Multi-Tenancy Bounded Context

> **Implementation Plan (proposed, deferred)**
>
> Captures a design that came out of an extended architecture discussion, so it survives across sessions instead of living only in chat history. **Not started yet.** Sequencing, per the user's own decision: finish the in-progress public API / API-key work (`docs/plans/8-public-api-key-auth.md`) first, then build this, then consider a broader refactor pass informed by having both features in place. Do not begin implementation from this file alone without re-confirming the plan is still current.
>
> This repo is open source and forked by third parties for arbitrary domains, so this plan deliberately illustrates the pattern with two small, generic, throwaway example resources (`Note`, `Project`) rather than any real business domain. A fork adopting this plan is expected to delete or replace those two example verticals with its own entities, keeping only the `Organization`/`OrganizationMembership`/authorization scaffolding underneath them.

## Context

This template today has exactly one bounded context: **Identity** (`User`, sessions, API keys — everything under `core/common/entities/user.py` and the auth-related commands/queries). Every resource in the system is implicitly "owned by the platform" or, at most, by a single user. There is no concept of an organization, team, or tenant, and the existing roadmap (`docs/plans/0-production-readiness-roadmap.md`, "Optional, and genuinely scale-dependent: multi-tenancy") already flags this as real, deliberately deferred future work — "a real domain-modeling exercise ... not a config toggle."

The goal this plan captures: let this template support **two kinds of CRUD resource side by side, permanently, decided per-feature rather than by a global switch**:

1. **Personal resources** — owned directly by one `user_id`. Needs nothing new; this is exactly the shape `ApiKey` (`docs/plans/8-public-api-key-auth.md`) already uses.
2. **Organization-scoped resources** — owned by an `organization_id`, accessible only to users who are members of that organization, with an organization-scoped role governing what a member can do inside it.

A single deployment can have both at once (a personal "my saved settings" resource next to an organization-scoped "shared project" resource, say) — this is closer to how GitHub repositories can be owned by either a user or an organization than to a single global "is this app single-tenant or multi-tenant" mode. A fork that never needs organizations never has to wire this feature in at all; a fork that does gets it without anything about `User` changing.

### Lessons pulled in from researching three real multi-tenancy implementations

Three existing open-source SaaS codebases were read (not just their docs) before finalizing this design, specifically to sanity-check the membership shape and the isolation strategy:

1. **https://github.com/Avatarctic/clean-architecture-saas** puts a single required `tenant_id` directly on the `User`/account row — a user can belong to exactly one tenant. This is simpler, but doesn't support one person belonging to more than one organization (a common real case — someone who is a member of one org and a guest/collaborator in another), and it means the identity entity itself has to change to add the concept.
2. **https://github.com/philipokiokio/FastAPI_SAAS_Template** and **https://github.com/apptension/saas-boilerplate** instead use a **join/membership entity** (`user_id`, `organization_id`, `role`, plus invitation-acceptance state on the same row) — a genuine many-to-many relationship, with the identity entity completely untouched. Both also happen to structure their codebase as separate "users" and "multi-tenancy" modules/apps, with the tenant-owned business modules depending on the membership module for scoping, not on the user module directly — independently arriving at the same three-context split this plan uses (see "Bounded contexts" below).
3. All three enforce tenant scoping by requiring every tenant-owned table to carry the tenant id and every query against it to filter by it — **none** of them do this automatically at the ORM/framework level (no reusable "auto-filtering base manager/repository" was found in any of them, confirmed by reading `apptension/saas-boilerplate`'s `packages/backend/apps/multitenancy/managers.py` specifically for one). This directly confirms the existing roadmap's own point: a missed `WHERE organization_id = ...` is a real, serious failure mode that has to be designed for deliberately (see "Defense in depth" below), not something a lighter or heavier framework solves for free.

This plan adopts lesson 2's membership shape (a join entity, not a column on `User`) and lesson 3's conclusion (shared schema + explicit scoping, with Postgres Row-Level Security as a deliberate second layer, exactly as the existing roadmap already recommends).

**A note on `apptension/saas-boilerplate` specifically, since it's the richest of the three and the one this plan leans on most for the membership/role *shape*:** it's a Django + GraphQL (Graphene) + Celery monorepo (NX, with an AWS CDK-deployed React frontend alongside it) — a full commercial SaaS platform, not a lean Clean Architecture backend. Its `apps/multitenancy` app (`Tenant`, `TenantMembership`, plus a full tenant-scoped custom-role/permission-catalog RBAC system: `Permission`, `OrganizationRole`, `OrganizationRolePermission`, `TenantMembershipRole`) is genuinely the most sophisticated of the three, but its actual Django code — ActiveRecord-style models carrying persistence, validation, and GraphQL-resolution concerns together — is the opposite of this repo's Entity/Protocol-port/CQRS/Dishka-provider separation, and isn't something to port directly. This plan borrows `apptension/saas-boilerplate`'s **shape** (the `Tenant`/`TenantMembership` split, membership-plus-invitation-state on one row, tenant-scoped roles) and reimplements it from scratch in this repo's own idiom (`Entity` subclasses, `Protocol` ports, `Permission[PermissionContext]`), not its Django ORM code, migrations, or GraphQL resolvers.

---

## Bounded contexts and the dependency direction between them

Three contexts, not two, with dependency flowing one way:

```
Identity (existing, untouched)     Organizations (this plan)          Example business domain (illustrative)
────────────────────────────       ──────────────────────────         ───────────────────────────────────────
User (login, credentials,      ←── OrganizationMembership         ←──  Project (organization-owned example)
 platform-level role)              (user_id, organization_id, role)    Note (personal, user-owned example)
```

- **Identity has zero knowledge of Organizations.** `User` never imports anything from the new context, and nothing here proposes changing `core/common/entities/user.py`. This mirrors exactly how `ApiKey` was added without `User` ever learning API keys exist.
- **Organizations depends on Identity only as a foreign reference** — `OrganizationMembership.user_id` is a plain `UserId`, the same kind of reference `ApiKey.user_id` already is. The Organizations context owns the membership table; `User` has no idea membership exists.
- **An organization-scoped business entity depends on Organizations for scoping and access control, not on `User` directly.** It needs "does the current user have (at least) this role in this organization," which is a question the Organizations context answers — never "is this user's role X," which would be conflating a platform-level concept with an org-scoped one.

**A platform-level role and an organization-scoped role are two independent axes, not one.** `UserRole` (`SUPER_ADMIN`/`ADMIN`/`USER`, already implemented in `core/common/entities/types_.py`) answers "what can this account do to the platform itself" — admin-managing-users, the existing `role_hierarchy.py`. `OrganizationMembership.role` (new: `OWNER`/`ADMIN`/`MEMBER`, defined below) answers "what can this account do inside one specific organization." A platform `SUPER_ADMIN` and an organization `MEMBER` are unrelated facts about the same account; neither role list is aware of the other.

### Where the membership check lives, and why

The check "is this user allowed to touch this organization's data" must not live in `User` (which shouldn't know what an organization is) and must not live inside a business entity's own validation (mixing a domain object with an authorization concern). It belongs exactly where every other permission check in this codebase already lives: a `Permission[PermissionContext]` implementation (`core/common/authorization/`), backed by a port.

Concretely, that port — `MembershipChecker` — belongs in `core/common/authorization/ports.py`, right next to the existing `AuthzUserFinder`, **not** as a private port defined inside whatever business context needs it first. `AuthzUserFinder` already establishes the precedent: a port that exists purely to serve the shared `authorize()` mechanism, reused by every `Permission` that needs it, rather than redefined per-feature. If `MembershipChecker` were instead defined privately inside (say) the example `Project` vertical, every future organization-scoped feature this template or a fork ever adds would need to redefine the same "is this user a member of this org" port for itself. One shared port, one shared `Permission`, reused by everything that needs organization scoping — mirroring how `CanManageRole`/`CanManageSubordinate` already share `ROLE_HIERARCHY`.

`Permission.is_satisfied_by()` is synchronous everywhere in this codebase (see `authorize.py`, `permissions.py`) — it operates on already-resolved data, never performs I/O itself. `MembershipChecker.get_role()` is async (it queries the database), so the membership lookup must happen **before** `authorize()` is called, with the result placed onto the `PermissionContext`. This is spelled out explicitly in the design below because it's an easy detail to get backwards.

### Toward a modular monolith (decided, sequenced for later)

**This is a decided direction for this codebase, not yet implemented — do not restructure the codebase from this note alone; it belongs in its own dedicated implementation plan, executed when sequencing allows.** The three-bounded-context split above (Identity / Organizations / an organization-scoped business domain) is, so far, only a *logical* separation within this repo's existing layer-first folder structure — `core/`, `inbound/`, `outbound/`, `main/`, each holding every bounded context's files side by side (e.g. `core/common/entities/user.py` and `core/common/entities/organization.py` sitting next to each other). As this repo accumulates more bounded contexts, it will eventually be reorganized physically into a **modular monolith**: one folder per bounded context, each internally still following this repo's own DDD/Clean Architecture/Hexagonal/CQRS conventions (its own `core/commands`, `core/queries`, `core/common`, `inbound`, `outbound`), with `main/` staying the single composition root wiring every module's providers together — still one deployable process, one database, no network boundary between modules, just a physical folder boundary matching a logical one that already exists.

The candidate modules currently anticipated — likely three, possibly a fourth once a real business domain is built on top — are:
- **Users** — the existing Identity context (`User`, sessions, API keys), unchanged in behavior, just relocated.
- **Organizations** — this plan's own bounded context.
- **Notifications** — email delivery only for now (the existing `EmailSender` port, `SendWelcomeEmail` handler, and `console`/`smtp` adapters already living under `core/common/`/`outbound/adapters/` today), anticipated to grow into other channels (SMS, WhatsApp, etc.) later — exactly the kind of growth that justifies giving it its own module boundary early, even before a second channel actually exists.
- Possibly a fourth module for whatever real, fork-specific business domain eventually gets built on top of Users/Organizations (the illustrative `Note`/`Project` verticals above are stand-ins for this, not a commitment to a specific fourth module).

When this is executed, it is its own dedicated implementation plan — a structural migration, not a feature — sized and sequenced separately from this plan and from `docs/plans/8-public-api-key-auth.md`, timed for once there are enough real bounded contexts for the physical separation to earn its cost. See the matching entry in `docs/plans/0-production-readiness-roadmap.md`.

**A deliberate, named exception to this project's standing rule of minimizing changes to the original template author's code.** That rule exists because the original author's code is, right now, at the highest quality and most battle-tested grade it will ever be from this user's own hands — every edit is a chance to introduce a regression into code that currently has none (see the `feature-delete test` and the `CoreProvider`/`WorkerProvider` precedent elsewhere in this repo's own conventions). A modular-monolith restructuring necessarily means moving that original code — `User`, its commands/queries, the existing DI providers — out of today's layer-first folders and into a new per-bounded-context layout. The user has explicitly decided this specific tradeoff is worth making, because the architectural payoff of physical bounded-context separation outweighs the risk of touching already-trusted code. This exception is scoped narrowly and deliberately: **relocation only** — moving files and updating import paths — never an occasion to also rewrite, refactor, or "improve" the original author's internal logic while it's already being touched. If the eventual migration plan finds itself wanting to change more than a file's location and its imports, that is a signal to stop and reconfirm the scope, not to proceed.

---

## Why this is safe to add without touching existing composition

This is the same shape of addition `ApiKey` was: a wholly new set of entities, ports, adapters, and DI bindings, with the existing composition touched only at the same kind of narrow, explicit seams `ApiKey`'s `GetOwnProfile` touch already established as safe (see `docs/plans/8-public-api-key-auth.md`'s "safe to add" section for the precedent this mirrors).

**Feature-delete test:** deleting `src/app/core/common/entities/organization.py`, `src/app/core/common/entities/organization_membership.py`, `src/app/core/common/authorization/ports.py`'s `MembershipChecker` addition, `src/app/core/common/authorization/permissions.py`'s `CanAccessOrganization`/`OrganizationAccessContext` addition, `src/app/core/common/authorization/current_organization_service.py`, every file under `core/commands/organizations/`, `core/queries/organizations/`, `outbound/adapters/sqla_organization_*.py`, `outbound/adapters/sqla_membership_checker.py`, `outbound/persistence_sqla/mappings/organization*.py`, `inbound/http/organizations/**`, and the example `Note`/`Project` verticals in full, plus reverting the one new provider-binding block in `main/ioc/core.py` and the one new migration, leaves `User`, `CoreProvider`'s existing bindings, `AuthzUserFinder`, `role_hierarchy.py`, and every existing use case completely unaffected.

---

## Design

### `Organization` entity

`src/app/core/common/entities/organization.py` (new):
```python
from typing import NewType
from uuid import UUID

from app.core.common.entities.base import Entity
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime

OrganizationId = NewType("OrganizationId", UUID)


class Organization(Entity[OrganizationId]):
    """
    A tenant boundary. Deliberately minimal -- no billing/plan/slug fields,
    since this is template scaffolding, not a real product; a fork adds
    whatever SaaS-specific fields it actually needs.
    """

    def __init__(
        self,
        *,
        id_: OrganizationId,
        name: str,
        created_by_user_id: UserId,
        created_at: UtcDatetime,
    ) -> None:
        super().__init__(id_=id_)
        self.name = name
        self.created_by_user_id = created_by_user_id
        self._created_at = created_at

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at
```

### `OrganizationMembership` entity, and how it models an invite

`src/app/core/common/entities/organization_membership.py` (new). Deliberately scoped down from the more elaborate reference implementations: an invitation targets an **existing** user (by user id), not an arbitrary email address for someone who hasn't signed up yet -- that "invite an email that doesn't have an account" flow is a real, separate enhancement, explicitly out of scope here (see "Deliberately out of scope" below), matching this plan's "no premature optimization" brief.

A pending invite and an active membership are the same row, distinguished by a nullable `accepted_at` -- exactly the `ApiKey.revoked_at` pattern:

```python
from enum import StrEnum
from typing import NewType
from uuid import UUID

from app.core.common.entities.base import Entity
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime

OrganizationMembershipId = NewType("OrganizationMembershipId", UUID)


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationMembership(Entity[OrganizationMembershipId]):
    def __init__(
        self,
        *,
        id_: OrganizationMembershipId,
        organization_id: OrganizationId,
        user_id: UserId,
        role: OrganizationRole,
        invited_by_user_id: UserId,
        created_at: UtcDatetime,
        accepted_at: UtcDatetime | None = None,
    ) -> None:
        super().__init__(id_=id_)
        self.organization_id = organization_id
        self.user_id = user_id
        self.role = role
        self.invited_by_user_id = invited_by_user_id
        self._created_at = created_at
        self.accepted_at = accepted_at

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at

    # A plain @property/setter over a private _accepted_at attribute, NOT
    # composite(UtcDatetime, ...) -- see the note right below this code
    # block for why a nullable UtcDatetime field specifically breaks
    # composite() in this SQLAlchemy version, confirmed by a real bug hit
    # and fixed in docs/plans/8-public-api-key-auth.md's Step 3.
    @property
    def accepted_at(self) -> UtcDatetime | None:
        return UtcDatetime(self._accepted_at) if self._accepted_at is not None else None

    @accepted_at.setter
    def accepted_at(self, value: UtcDatetime | None) -> None:
        self._accepted_at = value.value if value is not None else None

    @property
    def is_accepted(self) -> bool:
        return self._accepted_at is not None

    def accept(self, *, now: UtcDatetime) -> None:
        self.accepted_at = now
```

**A concrete lesson carried over from `docs/plans/8-public-api-key-auth.md`'s Step 3:** `accepted_at`, like `ApiKey.revoked_at`/`last_used_at`, is a nullable `UtcDatetime`-typed field. That plan's own Step 3 hit a real, two-part bug here: mapping a nullable `UtcDatetime` field with `composite(UtcDatetime, ...)` crashes on load (SQLAlchemy calls `UtcDatetime(None)` unconditionally when the column is `NULL`), and the first fix attempted -- a `None`-tolerant wrapper *function* used as the composite's `class_` -- fixes loading but then breaks writing instead, because SQLAlchemy generates a composite's column-extraction logic by introspecting `class_` as a dataclass, which a plain function isn't. **The actual, final fix used there: don't use `composite()` for a nullable `UtcDatetime` field at all.** Give `OrganizationMembership` a plain `accepted_at` `@property`/setter pair over a private `_accepted_at` attribute, mapped directly to a plain nullable `DateTime` column (no `composite()` involved) -- the `None`-check and the `UtcDatetime` wrap/unwrap happen in ordinary Python in the entity itself, exactly like `ApiKey.revoked_at`/`last_used_at` now do. Copy that pattern directly; do not reach for `composite()` for this field, and do not rediscover either half of this bug a second time.

The organization's creator becomes its first membership row, with `role=OWNER` and `accepted_at` already set (no self-invite needed) -- see `CreateOrganization` below.

### The shared authorization plumbing

`core/common/authorization/ports.py` (existing file, one addition):
```python
class MembershipChecker(Protocol):
    @abstractmethod
    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        """None if the user has no ACCEPTED membership in this organization."""
        ...
```

`core/common/authorization/role_hierarchy.py`-equivalent for organizations, and the new `Permission`, in `core/common/authorization/permissions.py` (existing file, additions):
```python
ORGANIZATION_ROLE_HIERARCHY: Final[Mapping[OrganizationRole, set[OrganizationRole]]] = {
    OrganizationRole.OWNER: {OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER},
    OrganizationRole.ADMIN: {OrganizationRole.ADMIN, OrganizationRole.MEMBER},
    OrganizationRole.MEMBER: {OrganizationRole.MEMBER},
}


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationAccessContext(PermissionContext):
    # member_role is resolved by calling MembershipChecker.get_role() BEFORE
    # authorize() is invoked -- is_satisfied_by() below is synchronous, like
    # every other Permission in this codebase, and never performs I/O itself.
    member_role: OrganizationRole | None
    minimum_role: OrganizationRole


class CanAccessOrganization(Permission[OrganizationAccessContext]):
    def is_satisfied_by(self, context: OrganizationAccessContext) -> bool:
        if context.member_role is None:
            return False
        return context.minimum_role in ORGANIZATION_ROLE_HIERARCHY.get(context.member_role, set())
```

`CurrentOrganizationService` (`core/common/authorization/current_organization_service.py`, new), mirroring `CurrentUserService`'s single-call ergonomics, resolving "which organization" from the request path (`/organizations/{organization_id}/...` -- see routing below) rather than from a credential:
```python
class OrganizationContextMissingError(BaseError): ...


class CurrentOrganizationService:
    def __init__(
        self,
        request: Request,
        current_user_service: CurrentUserService,
        membership_checker: MembershipChecker,
    ) -> None:
        self._request = request
        self._current_user_service = current_user_service
        self._membership_checker = membership_checker

    async def require_role(self, minimum_role: OrganizationRole) -> tuple[OrganizationId, User]:
        raw_id = self._request.path_params.get("organization_id")
        if raw_id is None:
            raise OrganizationContextMissingError
        organization_id = OrganizationId(UUID(raw_id))
        current_user = await self._current_user_service.get_current_user()
        member_role = await self._membership_checker.get_role(current_user.id_, organization_id)
        authorize(
            CanAccessOrganization(),
            context=OrganizationAccessContext(member_role=member_role, minimum_role=minimum_role),
        )
        return organization_id, current_user
```
Every organization-scoped command/query depends on this one service and calls `require_role()` once, exactly the way every existing command depends on `CurrentUserService.get_current_user()`.

### Commands and queries

Following the CQRS port split `ApiKey` already established (`core.commands` and `core.queries` never cross-import):

- **`CreateOrganization`** (command) -- any authenticated user may create an organization; creates the `Organization` row and, in the same transaction, an accepted `OrganizationMembership` row for the creator with `role=OWNER`.
- **`InviteOrganizationMember`** (command) -- requires `CurrentOrganizationService.require_role(OrganizationRole.ADMIN)` (only an OWNER or ADMIN may invite); creates a pending `OrganizationMembership` (`accepted_at=None`) for an existing user, looked up by username via the same `UserFinder` port `IssueApiKey` already reuses.
- **`AcceptOrganizationInvitation`** (command) -- authorization here is `context.subject.id_ == membership.user_id`, literally `CanManageSelf`'s existing shape, not `CanAccessOrganization` (the invitee isn't a member yet, so there is nothing for `MembershipChecker` to find); calls `membership.accept(now=...)`.
- **`RemoveOrganizationMember`** (command) -- requires `require_role(OrganizationRole.ADMIN)`; refuses to remove the last remaining `OWNER` (an invariant worth its own explicit unit test).
- **`ListMyOrganizations`** (query) -- the organizations the current user has an *accepted* membership in, plus their role in each.
- **`ListOrganizationMembers`** (query) -- requires `require_role(OrganizationRole.MEMBER)` (any member, not just admins, may see who else is in their organization); returns each member's role and pending/accepted status.

### HTTP routing shape

Path-scoped, mirroring this repo's existing `/api/v1/...` versioning discipline:

```
POST   /api/v1/organizations/                                    CreateOrganization
GET    /api/v1/organizations/                                    ListMyOrganizations
POST   /api/v1/organizations/{organization_id}/members/           InviteOrganizationMember
GET    /api/v1/organizations/{organization_id}/members/           ListOrganizationMembers
POST   /api/v1/organizations/{organization_id}/members/{membership_id}/accept/   AcceptOrganizationInvitation
DELETE /api/v1/organizations/{organization_id}/members/{membership_id}/          RemoveOrganizationMember
```

### The two example CRUD verticals: proving both resource shapes coexist

Small, deliberately generic, deliberately disposable -- the point is to prove the architecture, not to ship a real feature. Both are illustrative scaffolding a fork is expected to delete and replace with its own entities; only `Organization`/`OrganizationMembership`/the authorization plumbing above are meant to be kept long-term.

- **`Note`** (personal resource) -- `Note(id_, owner_user_id, title, body, created_at)`. Authorization: `context.subject.id_ == note.owner_user_id`, `CanManageSelf`'s existing shape, reused verbatim. Routes: `/api/v1/notes/...`, scoped to the caller only. Needs nothing from this plan's own scaffolding -- proves personal-resource CRUD needs zero organization concept.
- **`Project`** (organization-scoped resource) -- `Project(id_, organization_id, created_by_user_id, name, created_at)`. Authorization: `CurrentOrganizationService.require_role(OrganizationRole.MEMBER)` for read/list, `require_role(OrganizationRole.ADMIN)` for create/delete. Routes: `/api/v1/organizations/{organization_id}/projects/...`. Proves organization-scoped CRUD composes cleanly through the shared `MembershipChecker`/`CanAccessOrganization` plumbing.

### Defense in depth: Postgres Row-Level Security

Per the existing roadmap's own recommendation, app-layer scoping (the `CurrentOrganizationService`/`CanAccessOrganization` check above) should not be the *only* enforcement layer for `Project` and any future organization-owned table -- a missed `WHERE organization_id = ...` in some future query is a cross-tenant data leak, a severe-incident class of bug, not an ordinary one. All three reference implementations researched for this plan rely on app-layer filtering alone with no automatic base-manager/repository enforcement, which is exactly the gap RLS is meant to close. Concretely: a Postgres RLS policy on `projects` (and every future organization-owned table) keyed on a session-local `app.current_organization_id` setting, set once per request by the same session/transaction machinery `TransactionManager` already wraps. This is the one piece of this plan with no existing precedent anywhere in this codebase (no prior per-request Postgres session variable) -- prototype and test it in isolation before wiring it into the real migration.

### Deliberately out of scope

- **Billing/plans/subscriptions** -- this is a template, not a commercial product; a fork adds whatever billing model fits its own business.
- **Custom, tenant-defined roles and a permission catalog** (`apptension/saas-boilerplate` — https://github.com/apptension/saas-boilerplate — goes this far: organizations can define their own named roles with a configurable permission set via its `Permission`/`OrganizationRole`/`OrganizationRolePermission`/`TenantMembershipRole` models). Explicitly deferred -- the fixed `OWNER`/`ADMIN`/`MEMBER` enum above, mirroring `UserRole`'s own shape, is enough for a template; a fork that needs more can extend `OrganizationRole`'s hierarchy the same way `role_hierarchy.py` already models `UserRole`'s.
- **Inviting an email address with no existing account yet.** Real, common, and explicitly deferred -- see `OrganizationMembership`'s design note above.
- **An audit log.** The existing roadmap already separately flags "audit log for admin actions if sign-up is admin/invite-only" as its own item; `apptension/saas-boilerplate`'s tenant-scoped `ActionLog` model (JSON before/after diff, actor tracking; see `packages/backend/apps/multitenancy/models.py` in https://github.com/apptension/saas-boilerplate) is a good concrete shape for that *separate* roadmap item, worth reconsidering jointly with this plan when both are eventually prioritized, but is not part of this plan.

---

## Package layout

```
src/app/core/common/entities/organization.py                      # Organization entity
src/app/core/common/entities/organization_membership.py           # OrganizationMembership entity, OrganizationRole enum
src/app/core/common/authorization/ports.py                        # +MembershipChecker (appended to existing file)
src/app/core/common/authorization/permissions.py                  # +ORGANIZATION_ROLE_HIERARCHY, OrganizationAccessContext, CanAccessOrganization
src/app/core/common/authorization/current_organization_service.py # CurrentOrganizationService, OrganizationContextMissingError
src/app/core/common/factories/organization_id_factory.py
src/app/core/common/factories/organization_membership_id_factory.py

src/app/core/commands/ports/organization_repository.py            # add(), get_by_id(), get_membership_by_id(), add_membership(), count_owners()
src/app/core/commands/organization_exceptions.py                  # OrganizationNotFoundError, LastOwnerError, UnknownInviteeError
src/app/core/commands/create_organization.py
src/app/core/commands/invite_organization_member.py
src/app/core/commands/accept_organization_invitation.py
src/app/core/commands/remove_organization_member.py

src/app/core/queries/ports/organization_reader.py                 # OrganizationReader, OrganizationQm, ListMyOrganizationsQm, OrganizationMemberQm, ListOrganizationMembersQm
src/app/core/queries/list_my_organizations.py
src/app/core/queries/list_organization_members.py

src/app/outbound/adapters/sqla_organization_repository.py
src/app/outbound/adapters/sqla_organization_reader.py
src/app/outbound/adapters/sqla_membership_checker.py

src/app/outbound/persistence_sqla/mappings/organization.py            # organizations_table, map_organizations_table()
src/app/outbound/persistence_sqla/mappings/organization_membership.py # organization_memberships_table, map_organization_memberships_table()
src/app/outbound/persistence_sqla/alembic/versions/<ts>_add_organizations_and_memberships.py

src/app/inbound/http/organizations/__init__.py
src/app/inbound/http/organizations/router.py                      # make_organizations_router()
src/app/inbound/http/organizations/create_organization.py
src/app/inbound/http/organizations/list_my_organizations.py
src/app/inbound/http/organizations/invite_member.py
src/app/inbound/http/organizations/accept_invitation.py
src/app/inbound/http/organizations/remove_member.py
src/app/inbound/http/organizations/list_members.py

-- Example verticals (illustrative, deletable) --
src/app/core/common/entities/note.py
src/app/core/commands/{create,update,delete}_note.py
src/app/core/queries/{get,list}_notes.py (ports + adapters + mapping + migration + HTTP, same shape as above)
src/app/core/common/entities/project.py
src/app/core/commands/{create,delete}_project.py
src/app/core/queries/list_projects.py (ports + adapters + mapping + migration + HTTP, same shape as above)

tests/unit/core/common/entities/test_organization.py
tests/unit/core/common/entities/test_organization_membership.py
tests/unit/core/commands/organizations/...
tests/unit/core/queries/test_list_my_organizations.py
tests/unit/core/queries/test_list_organization_members.py
tests/integration/with_infra/organizations/...
```

Additive touches to existing files: one new provider-binding block in `main/ioc/core.py` (`organization_repository`, `organization_reader`, `membership_checker`, `current_organization_service`, plus the new commands/queries -- `CoreProvider` gains bindings the same way it already gained `GetOwnProfile`'s, never split or parameterized); one new sub-router registration in the top-level API router; one new mapping registration each in `mappings/all.py`; the roadmap/README checklist sync.

---

## Proposed Changes

Test file(s) before production file(s) per step, per this project's TDD convention. Numbered independently of `docs/plans/8-public-api-key-auth.md`'s steps -- this is its own plan, to be sequenced after that one is complete.

**Step 1 -- `Organization` + `OrganizationMembership` entities, `OrganizationRole`.**
- Test: entity-level tests mirroring `test_api_key.py`'s style -- a fresh membership is not accepted; `accept()` sets `accepted_at`; `is_accepted` reflects it.
- Production: the two entities above.

**Step 2 -- Shared authorization plumbing.**
- Test: `CanAccessOrganization.is_satisfied_by()` unit tests -- `member_role=None` always fails regardless of `minimum_role`; a role satisfies its own and lower minimums per `ORGANIZATION_ROLE_HIERARCHY`, never a higher one.
- Production: `MembershipChecker` port, `ORGANIZATION_ROLE_HIERARCHY`/`OrganizationAccessContext`/`CanAccessOrganization`.

**Step 3 -- `OrganizationRepository`/`OrganizationReader` ports + `Sqla*` adapters + mappings + migration.**
- Apply the `_optional_utc_datetime` lesson from `docs/plans/8-public-api-key-auth.md`'s Step 3 directly to `accepted_at`'s mapping -- do not skip this and rediscover the same crash.
- Test: integration tests constructing the adapters directly against `it_session`, mirroring `test_sqla_api_key_repository.py`/`test_sqla_api_key_reader.py`'s exact structure.
- Production: the two ports, two adapters, two mappings, the migration.

**Step 4 -- `SqlaMembershipChecker` + `CurrentOrganizationService`.**
- Test: unit tests with fakes -- known accepted membership resolves the right role; a pending (not yet accepted) membership resolves `None`; an unknown (user, organization) pair resolves `None`.
- Production: the adapter and the service.

**Step 5 -- `CreateOrganization`.**
- Test: unit + integration, mirroring `IssueApiKey`'s test structure -- creates the org and an accepted OWNER membership in the same transaction.
- Production: the command, its HTTP route, the provider binding.

**Step 6 -- `InviteOrganizationMember` + `AcceptOrganizationInvitation`.**
- Test: unit + integration -- non-ADMIN/OWNER inviter is rejected; invitee who isn't the accepting caller is rejected (`CanManageSelf` shape); double-accept is idempotent or explicitly rejected (decide and test one).
- Production: both commands, their HTTP routes, provider bindings.

**Step 7 -- `RemoveOrganizationMember`.**
- Test: unit + integration -- non-ADMIN/OWNER remover is rejected; removing the last OWNER is rejected with a dedicated `LastOwnerError`.
- Production: the command, its HTTP route, the provider binding.

**Step 8 -- `ListMyOrganizations` + `ListOrganizationMembers`.**
- Test: unit + integration -- scoping (only the caller's own accepted orgs; only a member of *this* org can list *its* members), pending vs. accepted status surfaced correctly.
- Production: both queries, their HTTP routes, provider bindings.

**Step 9 -- Example vertical: `Note` (personal resource).**
- Full TDD cycle for a minimal create/get/list/delete, proving personal-resource CRUD needs none of Steps 1-8's machinery.

**Step 10 -- Example vertical: `Project` (organization-scoped resource).**
- Full TDD cycle for a minimal create/get/list, proving organization-scoped CRUD composes correctly through `CurrentOrganizationService`.

**Step 11 -- Row-Level Security prototype (spike, not yet a committed design).**
- A dedicated, isolated integration test proving a `SET app.current_organization_id` + RLS policy on `projects` actually blocks a cross-organization row from being returned even when the application-layer check is (hypothetically) bypassed. Decide the session-variable-setting mechanism here before writing the real migration.

**Step 12 -- Dependency, docs, and roadmap/README checklist sync.**
- `docs/plans/0-production-readiness-roadmap.md` and `README.md` -- flip the multi-tenancy line from "planned" to done, in the style of this repo's other completed items.
- Add wiki documentation for the organizations concept, the membership/invite flow, and the two resource-ownership shapes.

---

## File Summary

| File | Purpose |
|---|---|
| `src/app/core/common/entities/organization.py` | `Organization` entity |
| `src/app/core/common/entities/organization_membership.py` | `OrganizationMembership` entity, `OrganizationRole` |
| `src/app/core/common/authorization/ports.py` (+`MembershipChecker`) | Shared port every organization-scoped `Permission` depends on |
| `src/app/core/common/authorization/permissions.py` (+`CanAccessOrganization`) | The one new `Permission`, reused by every future org-scoped feature |
| `src/app/core/common/authorization/current_organization_service.py` | Resolves "which organization, with what role" per request |
| `src/app/core/commands/{create,invite,accept,remove}_organization*.py` | The four organization-management commands |
| `src/app/core/queries/list_my_organizations.py`, `list_organization_members.py` | The two organization-management queries |
| `src/app/outbound/adapters/sqla_organization_repository.py` / `sqla_organization_reader.py` / `sqla_membership_checker.py` | Persistence adapters |
| `src/app/outbound/persistence_sqla/mappings/organization*.py` + migration | `organizations`/`organization_memberships` tables |
| `src/app/inbound/http/organizations/**` | The organization-management router group |
| `src/app/core/common/entities/note.py` + its commands/queries/routes | Example personal-resource vertical (illustrative, deletable) |
| `src/app/core/common/entities/project.py` + its commands/queries/routes | Example organization-scoped vertical (illustrative, deletable) |
| `src/app/main/ioc/core.py` (+bindings) | Registers the new commands/queries/services on the existing `CoreProvider` |

## Verification Plan

- **`make check`** -- lint + `mypy --strict` + `lint-imports` (confirms `core.commands`/`core.queries` still don't cross-import, and the new `inbound/http/organizations/` package respects the existing layering contracts) + fast unit tests.
- **`make test-docker`** -- full integration suite, including every new organizations/notes/projects test alongside the untouched pre-existing suites.
- **Manual verification**, using real entrypoints: sign up two accounts; account A creates an organization (confirm A is `OWNER`); A invites B; B, authenticated as themselves, accepts; confirm B can now list/create projects in A's organization at `OrganizationRole.MEMBER`, but cannot invite a third account until promoted to `ADMIN`; confirm account C (never invited) gets `403` on every one of A's organization's endpoints; confirm A's personal `Note`s are invisible to B and vice versa, proving the two resource shapes stay properly isolated from each other as well as across organizations.
