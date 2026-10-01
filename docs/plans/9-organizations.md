# Organizations: an Additive Multi-Tenancy Bounded Context

> **Implementation Plan (proposed, deferred)**
>
> Captures a design that came out of an extended architecture discussion, so it survives across sessions instead of living only in chat history. **Not started yet.** Sequencing, per the user's own decision: finish the in-progress public API / API-key work (`docs/plans/8-public-api-key-auth.md`) first, then build this, then consider a broader refactor pass informed by having both features in place. Do not begin implementation from this file alone without re-confirming the plan is still current.
>
> This repo is open source and forked by third parties for arbitrary domains, so this plan deliberately avoids illustrating the pattern with any invented business-domain example resource. See "Proving both resource shapes coexist" below for how the plan's own real, permanent organization-management surface (`ListMyOrganizations`, `ListOrganizationMembers`, plus the existing `GetOwnProfile`) already proves personal vs. organization-scoped resources coexist end-to-end, with nothing left over for a fork to delete afterward.

## Context

This template today has exactly one bounded context: **Identity** (`User`, sessions, API keys — everything under `core/common/entities/user.py` and the auth-related commands/queries). Every resource in the system is implicitly "owned by the platform" or, at most, by a single user. There is no concept of an organization, team, or tenant, and the existing roadmap (`docs/plans/0-production-readiness-roadmap.md`, "Optional, and genuinely scale-dependent: multi-tenancy") already flags this as real, deliberately deferred future work — "a real domain-modeling exercise ... not a config toggle."

The goal this plan captures: let this template support **two kinds of CRUD resource side by side, permanently, decided per-feature rather than by a global switch**:

1. **Personal resources** — owned directly by one `user_id`. Needs nothing new; this is exactly the shape `ApiKey` (`docs/plans/8-public-api-key-auth.md`) already uses.
2. **Organization-scoped resources** — owned by an `organization_id`, accessible only to users who are members of that organization, with an organization-scoped role governing what a member can do inside it.

A single deployment can have both at once (a personal "my saved settings" resource next to an organization-scoped "shared project" resource, say) — this is closer to how GitHub repositories can be owned by either a user or an organization than to a single global "is this app single-tenant or multi-tenant" mode. A fork that never needs organizations never has to wire this feature in at all; a fork that does gets it without anything about `User` changing.

### User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Create an organization | user | to create an organization | my team has a shared space I own | I become its OWNER immediately, no invitation needed<br>The name must follow `OrganizationName`'s rules, otherwise 400 |
| 2. Invite a member | organization OWNER or ADMIN | to invite an existing user by username | they can join | The invitation is pending, and expires after `ORGANIZATION_INVITATION_TTL_DAYS` (default 7)<br>A MEMBER can't invite (403)<br>Only an OWNER can invite someone as OWNER (403)<br>An existing member or live invitation is refused (409)<br>Re-inviting over an expired invitation renews it |
| 3. Accept or decline | invited user | to accept or decline an invitation | I decide which organizations I belong to | Accepting makes me a member; accepting twice is harmless<br>An expired invitation can't be accepted (410) but can be declined<br>Someone else's invitation looks like it doesn't exist (404) |
| 4. Stay private | outsider | not to be able to tell an organization exists | organizations stay private | Every organization-scoped request from a non-member gets 404, never 403 |
| 5. See organizations and members (Steps 7/8) | member | to see my organizations and their members | I know who I work with | Only organizations I've accepted, each with my role and its member count, paginated<br>Members are listed by username only; no email or phone number |
| 6. Remove, leave, change roles (Step 7) | OWNER or ADMIN, or any member for leaving | to remove members, change roles, and leave | membership stays current | Only an OWNER can remove or change another OWNER<br>The last OWNER can never be removed, demoted or leave |

### Lessons pulled in from researching three real multi-tenancy implementations

Three existing open-source SaaS codebases were read (not just their docs) before finalizing this design, specifically to sanity-check the membership shape and the isolation strategy:

1. **https://github.com/Avatarctic/clean-architecture-saas** puts a single required `tenant_id` directly on the `User`/account row — a user can belong to exactly one tenant. This is simpler, but doesn't support one person belonging to more than one organization (a common real case — someone who is a member of one org and a guest/collaborator in another), and it means the identity entity itself has to change to add the concept.
2. **https://github.com/philipokiokio/FastAPI_SAAS_Template** and **https://github.com/apptension/saas-boilerplate** instead use a **join/membership entity** (`user_id`, `organization_id`, `role`) — a genuine many-to-many relationship, with the identity entity completely untouched. Only `apptension/saas-boilerplate` also keeps invitation-acceptance state on that same row (`is_accepted`/`invitation_accepted_at`); `philipokiokio/FastAPI_SAAS_Template` has no pending state at all -- its invitations are shareable, revocable token links, and joining creates the member row directly (it also makes organization names globally unique, and has no last-admin protection). Both also happen to structure their codebase as separate "users" and "multi-tenancy" modules/apps, with the tenant-owned business modules depending on the membership module for scoping, not on the user module directly — independently arriving at the same three-context split this plan uses (see "Bounded contexts" below).
3. All three enforce tenant scoping by requiring every tenant-owned table to carry the tenant id and every query against it to filter by it — **none** of them do this automatically at the ORM/framework level (no reusable "auto-filtering base manager/repository" was found in any of them, confirmed by reading `apptension/saas-boilerplate`'s `packages/backend/apps/multitenancy/managers.py` specifically for one). This directly confirms the existing roadmap's own point: a missed `WHERE organization_id = ...` is a real, serious failure mode that has to be designed for deliberately (see "Defense in depth" below), not something a lighter or heavier framework solves for free.

This plan adopts lesson 2's membership shape (a join entity, not a column on `User`) and lesson 3's conclusion (shared schema + explicit scoping, with Postgres Row-Level Security as a deliberate second layer, exactly as the existing roadmap already recommends).

**Lesson 3, verified first-hand during Step 9 (the RLS spike).** Each repo was searched for `ROW LEVEL SECURITY`, `CREATE POLICY`, `current_setting`, `set_config` and `SET LOCAL`, and its tenant scoping was traced from route to query. None of the three uses Row-Level Security, per-tenant schemas, or per-request database session variables. All three connect as a single database user and scope every query by hand:
- `philipokiokio/FastAPI_SAAS_Template`: route dependencies (`member_dep`, `admin_rights_dep` in `src/organization/pipes/org_dep.py`) check membership, then each repository method adds its own `org_id` filter.
- `apptension/saas-boilerplate`: a GraphQL middleware (`apps/multitenancy/middleware.py`) attaches the tenant only for accepted members, then each resolver needs a policy decorator plus its own `.filter(tenant_id=...)`. A plain `Model.objects.all()` returns every tenant's rows.
- `Avatarctic/clean-architecture-saas`: middleware resolves the tenant from the subdomain or JWT, repositories filter by a `tenant_id` argument, and lookups by id are deliberately unscoped. Its audit-log route (`python/src/app/routers/audit.py`) queries with no tenant filter at all, guarded only by a permission tenant admins hold. That is exactly the forgotten-filter leak an enforced RLS policy turns into an empty result, and the reason this repo's RLS rollout is sequenced before search and file storage (`docs/plans/0-production-readiness-roadmap.md`). The leak comes from reading the code, not from running it.

**A note on `apptension/saas-boilerplate` specifically, since it's the richest of the three and the one this plan leans on most for the membership/role *shape*:** it's a Django + GraphQL (Graphene) + Celery monorepo (NX, with an AWS CDK-deployed React frontend alongside it) — a full commercial SaaS platform, not a lean Clean Architecture backend. Its `apps/multitenancy` app (`Tenant`, `TenantMembership`, plus a full tenant-scoped custom-role/permission-catalog RBAC system: `Permission`, `OrganizationRole`, `OrganizationRolePermission`, `TenantMembershipRole`) is genuinely the most sophisticated of the three, but its actual Django code — ActiveRecord-style models carrying persistence, validation, and GraphQL-resolution concerns together — is the opposite of this repo's Entity/Protocol-port/CQRS/Dishka-provider separation, and isn't something to port directly. This plan borrows `apptension/saas-boilerplate`'s **shape** (the `Tenant`/`TenantMembership` split, membership-plus-invitation-state on one row, tenant-scoped roles) and reimplements it from scratch in this repo's own idiom (`Entity` subclasses, `Protocol` ports, `Permission[PermissionContext]`), not its Django ORM code, migrations, or GraphQL resolvers.

---

## Bounded contexts and the dependency direction between them

Three contexts, not two, with dependency flowing one way:

```
Identity (existing, untouched)     Organizations (this plan)
────────────────────────────       ──────────────────────────
User (login, credentials,      ←── OrganizationMembership
 platform-level role)              (user_id, organization_id, role)
```

- **Identity has zero knowledge of Organizations.** `User` never imports anything from the new context, and nothing here proposes changing `core/common/entities/user.py`. This mirrors exactly how `ApiKey` was added without `User` ever learning API keys exist.
- **Organizations depends on Identity only as a foreign reference** — `OrganizationMembership.user_id` is a plain `UserId`, the same kind of reference `ApiKey.user_id` already is. The Organizations context owns the membership table; `User` has no idea membership exists.
- **An organization-scoped business entity depends on Organizations for scoping and access control, not on `User` directly.** It needs "does the current user have (at least) this role in this organization," which is a question the Organizations context answers — never "is this user's role X," which would be conflating a platform-level concept with an org-scoped one.

**A platform-level role and an organization-scoped role are two independent axes, not one.** `UserRole` (`SUPER_ADMIN`/`ADMIN`/`USER`, already implemented in `core/common/entities/types_.py`) answers "what can this account do to the platform itself" — admin-managing-users, the existing `role_hierarchy.py`. `OrganizationMembership.role` (new: `OWNER`/`ADMIN`/`MEMBER`, defined below) answers "what can this account do inside one specific organization." A platform `SUPER_ADMIN` and an organization `MEMBER` are unrelated facts about the same account; neither role list is aware of the other.

### Where the membership check lives, and why

The check "is this user allowed to touch this organization's data" must not live in `User` (which shouldn't know what an organization is) and must not live inside a business entity's own validation (mixing a domain object with an authorization concern). It belongs exactly where every other permission check in this codebase already lives: a `Permission[PermissionContext]` implementation (`core/common/authorization/`), backed by a port.

Concretely, that port — `MembershipChecker` — belongs in `core/common/authorization/` (its own new `organization_ports.py`, next to the existing `ports.py` and its `AuthzUserFinder`, so the original file stays untouched), **not** as a private port defined inside whatever business context needs it first. `AuthzUserFinder` already establishes the precedent: a port that exists purely to serve the shared `authorize()` mechanism, reused by every `Permission` that needs it, rather than redefined per-feature. If `MembershipChecker` were instead defined privately inside whatever organization-scoped feature needs it first, every future organization-scoped feature this template or a fork ever adds would need to redefine the same "is this user a member of this org" port for itself. One shared port, one shared `Permission`, reused by everything that needs organization scoping — mirroring how `CanManageRole`/`CanManageSubordinate` already share `ROLE_HIERARCHY`.

`Permission.is_satisfied_by()` is synchronous everywhere in this codebase (see `authorize.py`, `permissions.py`) — it operates on already-resolved data, never performs I/O itself. `MembershipChecker.get_role()` is async (it queries the database), so the membership lookup must happen **before** `authorize()` is called, with the result placed onto the `PermissionContext`. This is spelled out explicitly in the design below because it's an easy detail to get backwards.

### Toward a modular monolith (decided, sequenced for later)

**This is a decided direction for this codebase, not yet implemented — do not restructure the codebase from this note alone; it belongs in its own dedicated implementation plan, executed when sequencing allows.** The three-bounded-context split above (Identity / Organizations / an organization-scoped business domain) is, so far, only a *logical* separation within this repo's existing layer-first folder structure — `core/`, `inbound/`, `outbound/`, `main/`, each holding every bounded context's files side by side (e.g. `core/common/entities/user.py` and `core/common/entities/organization.py` sitting next to each other). As this repo accumulates more bounded contexts, it will eventually be reorganized physically into a **modular monolith**: one folder per bounded context, each internally still following this repo's own DDD/Clean Architecture/Hexagonal/CQRS conventions (its own `core/commands`, `core/queries`, `core/common`, `inbound`, `outbound`), with `main/` staying the single composition root wiring every module's providers together — still one deployable process, one database, no network boundary between modules, just a physical folder boundary matching a logical one that already exists.

The candidate modules currently anticipated — likely three, possibly a fourth once a real business domain is built on top — are:
- **Users** — the existing Identity context (`User`, sessions, API keys), unchanged in behavior, just relocated.
- **Organizations** — this plan's own bounded context.
- **Notifications** — email delivery only for now (the existing `EmailSender` port, `SendWelcomeEmail` handler, and `console`/`smtp` adapters already living under `core/common/`/`outbound/adapters/` today), anticipated to grow into other channels (SMS, WhatsApp, etc.) later — exactly the kind of growth that justifies giving it its own module boundary early, even before a second channel actually exists.
- Possibly a fourth module for whatever real, fork-specific business domain eventually gets built on top of Users/Organizations -- not a commitment to a specific fourth module, since this plan deliberately ships no illustrative business-domain vertical of its own (see "Proving both resource shapes coexist" below).

When this is executed, it is its own dedicated implementation plan — a structural migration, not a feature — sized and sequenced separately from this plan and from `docs/plans/8-public-api-key-auth.md`, timed for once there are enough real bounded contexts for the physical separation to earn its cost. See the matching entry in `docs/plans/0-production-readiness-roadmap.md`.

**A deliberate, named exception to this project's standing rule of minimizing changes to the original template author's code.** That rule exists because the original author's code is, right now, at the highest quality and most battle-tested grade it will ever be from this user's own hands — every edit is a chance to introduce a regression into code that currently has none (see the `feature-delete test` and the `CoreProvider`/`WorkerProvider` precedent elsewhere in this repo's own conventions). A modular-monolith restructuring necessarily means moving that original code — `User`, its commands/queries, the existing DI providers — out of today's layer-first folders and into a new per-bounded-context layout. The user has explicitly decided this specific tradeoff is worth making, because the architectural payoff of physical bounded-context separation outweighs the risk of touching already-trusted code. This exception is scoped narrowly and deliberately: **relocation only** — moving files and updating import paths — never an occasion to also rewrite, refactor, or "improve" the original author's internal logic while it's already being touched. If the eventual migration plan finds itself wanting to change more than a file's location and its imports, that is a signal to stop and reconfirm the scope, not to proceed.

---

## Why this is safe to add without touching existing composition

This is the same shape of addition `ApiKey` was: a wholly new set of entities, ports, adapters, and DI bindings, with the existing composition touched only at the same kind of narrow, explicit seams `ApiKey`'s `GetOwnProfile` touch already established as safe (see `docs/plans/8-public-api-key-auth.md`'s "safe to add" section for the precedent this mirrors).

**Feature-delete test:** deleting `src/app/core/common/entities/organization.py`, `src/app/core/common/entities/organization_membership.py`, `src/app/core/common/authorization/organization_ports.py` (`MembershipChecker`), `src/app/core/common/authorization/organization_permissions.py` (`CanAccessOrganization`/`OrganizationAccessContext`), `src/app/core/common/authorization/current_organization_service.py`, every file under `core/commands/organizations/`, `core/queries/organizations/`, `outbound/adapters/sqla_organization_*.py`, `outbound/adapters/sqla_membership_checker.py`, `outbound/persistence_sqla/mappings/organization*.py`, `inbound/http/organizations/**`, plus reverting the one new provider-binding block in `main/ioc/core.py` and the one new migration, leaves `User`, `CoreProvider`'s existing bindings, `AuthzUserFinder`, `role_hierarchy.py`, and every existing use case completely unaffected.

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

**Invitations are for logged-in, existing accounts only -- deliberately.** Unlike `apptension/saas-boilerplate` (which can invite an email address that has no account yet, and therefore needs a signed email token to prove the invitee's identity), every invitation here targets an existing, active user, and accepting or declining requires being logged in *as* that user. That removes the need for invitation tokens entirely: identity is proven by the ordinary session, not by possession of a link. It also rules out `philipokiokio/FastAPI_SAAS_Template`'s shareable-link model, where anyone holding a (possibly leaked) link could join.

**Invitation expiry (`expires_at`).** A pending invitation expires after a configurable number of days (`ORGANIZATION_INVITATION_TTL_DAYS`, default 7, with its own `test_loader.py` env-var test). `OrganizationMembership` gains a nullable `expires_at` (set on every pending invite, `None` on the creator's owner row and cleared on accept) and an `is_expired(now)` method; it is a plain nullable `@property`/setter over `_expires_at`, exactly like `accepted_at`, never `composite()`. Consequences, each with its own test: accepting an expired invitation raises `InvitationExpiredError` (HTTP **410 Gone** -- it existed, but no longer can be used); declining an expired invitation is still allowed (it just deletes the row); re-inviting a user whose only row is an *expired pending* invitation **refreshes that same row** (new role, inviter, `created_at`, `expires_at`) instead of raising `MembershipAlreadyExistsError`, since the unique `(organization_id, user_id)` constraint rules out a second row; `ListMyInvitations` excludes expired invitations; `ListOrganizationMembers` shows each pending row's `expires_at` so admins can see which invitations have lapsed. Expiry never affects `MembershipChecker`, because a pending invitation grants no role in the first place.

**Telling the invitee: an invitation email via a domain event.** `InviteOrganizationMember` records an `OrganizationInvitationCreatedEvent` (organization id and name, invitee id and email, inviter's username, offered role, `expires_at`), and a new `SendOrganizationInvitationEmail` handler sends the invitee an email saying who invited them, to which organization, with what role, until when, and that they can accept from their pending invitations once logged in. It reuses the existing domain-event/outbox/`EmailSender` machinery exactly like `SendWelcomeEmail`, with `DISPATCH_MODE = "background"` -- so, per this template's smallest-viable-infrastructure principle, it runs inline in the web process when Celery is disabled and through the worker when it's enabled. The email carries no token or accept link that works without logging in, consistent with the rule above.

### The shared authorization plumbing

`core/common/authorization/organization_ports.py` (new file, next to -- not inside -- the original author's `ports.py`, so the feature stays purely additive; `ports.py` is left untouched):
```python
class MembershipChecker(Protocol):
    @abstractmethod
    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        """None if the user has no ACCEPTED membership in this organization."""
        ...
```

`core/common/authorization/role_hierarchy.py`-equivalent for organizations, and the new `Permission`, in `core/common/authorization/organization_permissions.py` (new file, for the same additive reason -- `permissions.py` and `role_hierarchy.py` are left untouched):
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

`CurrentOrganizationService` (`core/common/authorization/current_organization_service.py`, new), mirroring `CurrentUserService`'s single-call ergonomics. Unlike an earlier draft of this plan, it does **not** read `Request.path_params` itself -- it takes an already-parsed `organization_id: OrganizationId` argument instead, exactly matching this repo's existing convention for a UUID path parameter (`src/app/inbound/http/users/grant_admin.py`'s `user_id: Annotated[UUID, Path()]`): each organization-scoped route declares `organization_id: Annotated[UUID, Path()]`, so FastAPI/pydantic validates the UUID format before the handler body ever runs, and a malformed id in the URL 422s automatically, with no custom parsing or exception needed inside this service. This also means there's no code path left in the service that could ever hit a "missing from the path" case -- FastAPI's own routing guarantees the parameter exists before the handler runs -- so an earlier draft's `OrganizationContextMissingError` and the service's own `Request` dependency are both dropped as unnecessary:
```python
class CurrentOrganizationService:
    def __init__(
        self,
        current_user_service: CurrentUserService,
        membership_checker: MembershipChecker,
    ) -> None:
        self._current_user_service = current_user_service
        self._membership_checker = membership_checker

    async def require_role(
        self, organization_id: OrganizationId, minimum_role: OrganizationRole
    ) -> tuple[OrganizationId, User]:
        current_user = await self._current_user_service.get_current_user()
        member_role = await self._membership_checker.get_role(current_user.id_, organization_id)
        authorize(
            CanAccessOrganization(),
            context=OrganizationAccessContext(member_role=member_role, minimum_role=minimum_role),
        )
        return organization_id, current_user
```
**404 for non-members, 403 for members below the required role.** `require_role` distinguishes the two failure cases instead of raising `AuthorizationError` for both: when `member_role is None` (no accepted membership -- a stranger, a still-pending invitee, or a member of a different organization) it raises `OrganizationNotFoundError` (HTTP **404**) *before* `authorize()` runs, so an outsider can't even confirm the organization exists; only a genuine member whose role is too low (e.g. a `MEMBER` attempting an `ADMIN` action) gets `AuthorizationError` (HTTP **403**) -- they already know the organization exists, so hiding it gains nothing and 403 states the real reason. This matches the reference implementations: `apptension/saas-boilerplate` resolves no tenant at all for a non-member, `philipokiokio/FastAPI_SAAS_Template` returns 404.

Every organization-scoped command/query depends on this one service and calls `require_role(organization_id, minimum_role)` once, exactly the way every existing command depends on `CurrentUserService.get_current_user()`; the HTTP handler is responsible for extracting `organization_id` from its own `Annotated[UUID, Path()]` parameter and passing it through.

### Commands and queries

Following the CQRS port split `ApiKey` already established (`core.commands` and `core.queries` never cross-import):

- **`CreateOrganization`** (command) -- any authenticated user may create an organization; creates the `Organization` row and, in the same transaction, an accepted `OrganizationMembership` row for the creator with `role=OWNER`.
- **`InviteOrganizationMember`** (command) -- requires `CurrentOrganizationService.require_role(organization_id, OrganizationRole.ADMIN)` (only an OWNER or ADMIN may invite); creates a pending `OrganizationMembership` (`accepted_at=None`) for an existing user, looked up by username via the same `UserFinder` port `IssueApiKey` already reuses. Takes an explicit `role: OrganizationRole` chosen by the inviter for the invitee (defaulting to `MEMBER`). Granting `OrganizationRole.OWNER` specifically requires the inviter's own resolved role to already be `OWNER` -- raises the new `CannotGrantOwnerRoleError` otherwise. This mirrors `apptension/saas-boilerplate`'s `CreateTenantInvitationSerializer`, which enforces exactly this "only an existing owner can grant the owner role" rule -- not a blanket "an inviter can only grant a role at or below their own" (an ADMIN may still invite another ADMIN). Inviting a user who already has a membership row in this organization (pending or accepted) is checked for explicitly **before** insert and raised as a domain error (`MembershipAlreadyExistsError`, HTTP 409), rather than surfacing the unique `(organization_id, user_id)` constraint as a raw database `IntegrityError` -- mirroring `apptension/saas-boilerplate`'s "Invitation already exists".
- **`AcceptOrganizationInvitation`** (command) -- authorization here is `context.subject.id_ == membership.user_id`, literally `CanManageSelf`'s existing shape, not `CanAccessOrganization` (the invitee isn't a member yet, so there is nothing for `MembershipChecker` to find). **Idempotent**, mirroring `RevokeApiKey`'s established pattern for a nullable, set-once timestamp (`revoked_at`): `if not membership.is_accepted: membership.accept(now=...)`, with no second commit on a repeat call. A retried or replayed accept request is therefore safe rather than erroring -- this repo's own closer precedent than any of the three reference repos researched for this plan, none of which fire a notification or other side effect on accept that idempotency would need to additionally guard against here. This settles Step 6 below's previously open "decide and test one" question.
- **`DeclineOrganizationInvitation`** (command) -- the invitee turns down their own pending invitation, which deletes the pending row (`apptension/saas-boilerplate` does exactly this). Same authorization shape as `AcceptOrganizationInvitation`: only the invitee themselves (`membership.user_id == caller`), and only while it is still pending -- declining an already-accepted membership is not a decline, it's leaving (see `RemoveOrganizationMember`).
- **`RemoveOrganizationMember`** (command) -- deletes a membership row, pending or accepted. Rules, taken from `apptension/saas-boilerplate`'s `DeleteTenantMembershipMutation`:
  - **Removing yourself (leaving) is always allowed** to any member, with no `ADMIN` requirement -- otherwise a plain `MEMBER` could never leave an organization (`philipokiokio/FastAPI_SAAS_Template` also has a dedicated "leave" endpoint).
  - **Removing someone else** requires `require_role(organization_id, OrganizationRole.ADMIN)`. Deleting a *pending* row this way is how an admin revokes an invitation.
  - **Only an `OWNER` may remove another `OWNER`** -- an `ADMIN` may remove admins and members, never an owner.
  - **The last remaining accepted `OWNER` can never be removed**, including by leaving -- raises `LastOwnerError` (an invariant worth its own explicit unit test). Transferring ownership first (promote someone else to `OWNER`) is the way out.
- **`ChangeOrganizationMemberRole`** (command) -- changes an existing member's role; requires `require_role(organization_id, OrganizationRole.ADMIN)`. Rules, taken from `apptension/saas-boilerplate`'s `UpdateTenantMembershipSerializer`: only an `OWNER` may grant the `OWNER` role (same rule as inviting); only an `OWNER` may change the role of another `OWNER`; demoting the last remaining accepted `OWNER` raises `LastOwnerError`. This is also how ownership is transferred.
- **`ListMyOrganizations`** (query) -- the organizations the current user has an *accepted* membership in, plus their role in each, plus each organization's `member_count`. A plain `WHERE user_id = :caller` query with no membership-role check at all, since "which organizations am I in" depends only on identity, never on organization-scoped authorization -- see "Proving both resource shapes coexist" below.
- **`ListOrganizationMembers`** (query) -- requires `require_role(organization_id, OrganizationRole.MEMBER)` (any member, not just admins, may see who else is in their organization); returns each member's `username`, role and pending/accepted status, plus the organization's `member_count`. `username` is the **only** personal detail exposed about a member -- never email or phone number -- since every member of an organization can call this query, and a member list keyed only by user id would be unusable in a UI.
- **`ListMyInvitations`** (query) -- the current user's own **pending** invitations (`accepted_at IS NULL`), across every organization. Like `ListMyOrganizations`, it is user-scoped, not organization-scoped: a plain `WHERE user_id = :caller` query with no `CanAccessOrganization` check at all -- the invitee isn't a member yet, so an organization-scoped check would reject them by definition. Each row carries the `organization_id` and `membership_id` that `AcceptOrganizationInvitation`'s route needs, plus the organization's name, the offered role, the inviter's `username`, and when the invite was sent. This closes what would otherwise be a gap: without it, an invitee has no way to discover which invitations are waiting for them, or the ids needed to accept one. Kept separate from `ListMyOrganizations` (rather than folding pending invites into it with a flag, as `apptension/saas-boilerplate`'s "my tenants" list does) so that query keeps one meaning: "the organizations I am a member of".
- **Member count (`member_count`)** -- every application with organizations eventually needs to show how many members an organization has, so both queries above surface it. It counts **accepted** memberships only; pending invitations are not members yet (they are still listed, with their pending status, by `ListOrganizationMembers`). This is a display/read concern, so it lives on the query-side `OrganizationReader` (an aggregate `COUNT` in `SqlaOrganizationReader`, never by loading every membership row), **not** on the command-side `OrganizationRepository` -- whose `count_owners()` exists only to enforce `LastOwnerError`. A command-side member count would only be warranted by a write-side rule such as a per-organization member limit, which is not part of this plan (billing/plans are out of scope).

### HTTP routing shape

Path-scoped, mirroring this repo's existing `/api/v1/...` versioning discipline:

```
POST   /api/v1/organizations/                                    CreateOrganization
GET    /api/v1/organizations/                                    ListMyOrganizations
GET    /api/v1/organizations/invitations/                        ListMyInvitations
POST   /api/v1/organizations/{organization_id}/members/           InviteOrganizationMember
GET    /api/v1/organizations/{organization_id}/members/           ListOrganizationMembers
POST   /api/v1/organizations/{organization_id}/members/{membership_id}/accept/   AcceptOrganizationInvitation
POST   /api/v1/organizations/{organization_id}/members/{membership_id}/decline/  DeclineOrganizationInvitation
PATCH  /api/v1/organizations/{organization_id}/members/{membership_id}/          ChangeOrganizationMemberRole
DELETE /api/v1/organizations/{organization_id}/members/{membership_id}/          RemoveOrganizationMember (also "leave", when it's the caller's own membership)
```

### Proving both resource shapes coexist, without inventing example verticals

An earlier draft of this plan illustrated "personal resource" vs. "organization-scoped resource" with two throwaway example entities (`Note`, `Project`). On reflection, that's unnecessary scope: this plan's own real, permanent surface already proves the same architectural point end-to-end, with nothing left over for a fork to delete afterward --

- **Personal/user-scoped GET, zero organization concept:** `GetOwnProfile` (existing, already shared verbatim between the private app and the public API per `docs/plans/8-public-api-key-auth.md`) is the existing proof that a personal resource needs nothing from this plan's scaffolding. `ListMyOrganizations` (Step 8) is a second instance of the same shape -- a plain `WHERE user_id = :caller` query with no membership-role check at all, since "which organizations am I in" depends only on identity, never on organization-scoped authorization.
- **Organization-scoped GET, requiring membership:** `ListOrganizationMembers` (Step 8) is the proof that an organization-scoped *read* composes correctly through the shared `MembershipChecker`/`CurrentOrganizationService`/`CanAccessOrganization` plumbing -- deliberately gated at the lowest role, `OrganizationRole.MEMBER`, so any member (not just an OWNER/ADMIN) can see who else is in their organization.
- **Organization-scoped WRITE, requiring membership + role:** the four organization-management commands themselves (`CreateOrganization`, `InviteOrganizationMember`, `AcceptOrganizationInvitation`, `RemoveOrganizationMember`) are the organization-scoped *write* proof, already gated at `OrganizationRole.ADMIN` where appropriate.

This keeps this plan's own stated intent from the top of this document -- illustrating the pattern without any real business domain -- but does it with resources this template needs to ship anyway, instead of inventing `Note`/`Project` purely as a demonstration. A fork adopting this plan has nothing extra to delete: every file this plan adds is meant to be kept.

### Defense in depth: Postgres Row-Level Security

Per the existing roadmap's own recommendation, app-layer scoping (the `CurrentOrganizationService`/`CanAccessOrganization` check above) should not be the *only* enforcement layer for `organization_memberships` and any future organization-owned table -- a missed `WHERE organization_id = ...` in some future query is a cross-tenant data leak, a severe-incident class of bug, not an ordinary one. All three reference implementations researched for this plan rely on app-layer filtering alone with no automatic base-manager/repository enforcement, which is exactly the gap RLS is meant to close. Concretely: a Postgres RLS policy on `organization_memberships` (and every future organization-owned table) keyed on a session-local `app.current_organization_id` setting, set once per request by the same session/transaction machinery `TransactionManager` already wraps. This is the one piece of this plan with no existing precedent anywhere in this codebase (no prior per-request Postgres session variable) -- prototype and test it in isolation before wiring it into the real migration.

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
src/app/core/common/authorization/organization_ports.py           # MembershipChecker (new file; ports.py untouched)
src/app/core/common/authorization/organization_permissions.py     # ORGANIZATION_ROLE_HIERARCHY, OrganizationAccessContext, CanAccessOrganization (new file; permissions.py untouched)
src/app/core/common/authorization/current_organization_service.py # CurrentOrganizationService
src/app/core/common/factories/organization_id_factory.py
src/app/core/common/factories/organization_membership_id_factory.py

src/app/core/commands/ports/organization_repository.py            # add(), get_by_id(), get_membership_by_id(), add_membership(), count_owners() (+ membership lookup by user and delete, added in the steps that need them)
src/app/core/commands/organization_exceptions.py                  # LastOwnerError, UnknownInviteeError, CannotGrantOwnerRoleError, MembershipAlreadyExistsError, MembershipNotFoundError, InvitationExpiredError
src/app/core/common/organization_exceptions.py                    # InvalidMembershipExpiryError -- raised by the OrganizationMembership entity itself when accepted_at/expires_at aren't exactly one-set (a pending invite must expire, an accepted membership must not); a programming error with no HTTP mapping
src/app/core/common/authorization/organization_exceptions.py      # OrganizationNotFoundError -- raised by CurrentOrganizationService, so it lives in core.common (commands AND queries both need it)
src/app/core/commands/create_organization.py
src/app/core/commands/invite_organization_member.py
src/app/core/commands/accept_organization_invitation.py
src/app/core/commands/remove_organization_member.py

src/app/core/queries/ports/organization_reader.py                 # OrganizationReader, OrganizationQm, ListMyOrganizationsQm, OrganizationMemberQm, ListOrganizationMembersQm
src/app/core/queries/list_my_organizations.py
src/app/core/queries/list_organization_members.py
src/app/core/queries/list_my_invitations.py

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
src/app/inbound/http/organizations/list_my_invitations.py

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

**Step 6 -- `InviteOrganizationMember` + `AcceptOrganizationInvitation` + `DeclineOrganizationInvitation`, with invitation expiry designed in from the start.**
- Test: unit + integration -- `OrganizationMembership.expires_at`/`is_expired(now)` (entity), and `expires_at` round-tripping through the repository (nullable, so a plain column, not `composite()`), plus `ORGANIZATION_INVITATION_TTL_DAYS`' loader test; non-ADMIN/OWNER inviter is rejected; a duplicate invite raises `MembershipAlreadyExistsError` (409), never a raw `IntegrityError`, while re-inviting over an *expired* pending row refreshes it; an invite's `expires_at` is `now + TTL`; someone else's invitation, whether accepted or declined, is reported as `MembershipNotFoundError` (404, so its existence isn't revealed); an unknown or inactive invitee username raises `UnknownInviteeError` (404); granting OWNER without being OWNER raises `CannotGrantOwnerRoleError` (403); double-accept is idempotent (decided above); accepting an expired invitation raises `InvitationExpiredError` (410); declining deletes only the caller's own still-pending row, expired or not.
- Production: the entity/mapping change and its migration, the setting, the three commands, their HTTP routes, provider bindings.

**Step 6b -- Invitation email.**
- Test: unit tests for `OrganizationInvitationCreatedEvent` (payload round-trip, like `test_user_registered.py`) and for `SendOrganizationInvitationEmail` (background dispatch mode; sends the right recipient/content); `InviteOrganizationMember` records the event; integration test that inviting stages the handler's outbox row, mirroring `test_create_user.py`'s welcome-email assertion.
- Production: the event, the handler, its registration in the handler registry.

**Step 7 -- `RemoveOrganizationMember` (including leaving) + `ChangeOrganizationMemberRole`.**
- Test: unit + integration -- any member may remove themselves (leave); removing someone else requires ADMIN; an ADMIN cannot remove an OWNER; an admin can revoke a pending invitation; the last OWNER can never be removed, left, or demoted (`LastOwnerError`); only an OWNER may grant OWNER or change another OWNER's role.
- Production: both commands, their HTTP routes, provider bindings.

**Step 8 -- `ListMyOrganizations` + `ListOrganizationMembers` + `ListMyInvitations`.**
- Test: unit + integration -- scoping (only the caller's own accepted orgs; only a member of *this* org can list *its* members), pending vs. accepted status surfaced correctly, `member_count` counts only that organization's accepted memberships (a pending invite and another organization's members never count); `ListOrganizationMembers` exposes each member's `username` but never email/phone; `ListMyInvitations` returns only the caller's own *pending* invitations (never an accepted membership, never someone else's invite) and requires no organization membership to call.
- Production: both queries, their HTTP routes, provider bindings.

**Step 9 -- Row-Level Security prototype (spike, not yet a committed design).**
- A dedicated, isolated integration test proving a `SET app.current_organization_id` + RLS policy on `organization_memberships` (the one organization-owned table this plan actually ships, now that no example `Project` table exists) actually blocks a cross-organization row from being returned even when the application-layer check is (hypothetically) bypassed. Decide the session-variable-setting mechanism here before writing the real migration.
- **Done as a spike:** `tests/integration/with_infra/organizations/test_rls_spike.py`. No production code, migration or wiring was added; every policy, grant and role is created inside one transaction and rolled back. Findings, for whoever writes the real RLS plan:
  1. **Mechanism:** `set_config('app.current_organization_id', <id>, true)`. The `true` makes the value transaction-local, like `SET LOCAL`, so it can't leak into the next request on a pooled connection. With a policy of `organization_id = current_setting('app.current_organization_id', true)::uuid`, the policy works: an unfiltered `SELECT` returns only the current organization's rows.
  2. **It fails closed:** `current_setting(..., true)` returns NULL when the variable was never set, so a request that forgets to set it sees no rows at all, never another organization's.
  3. **Blocker: superusers bypass RLS.** The app and the tests connect as `postgres`, a superuser, and superusers ignore every policy (pinned by `test_a_superuser_bypasses_row_level_security`). Real enforcement needs the app to connect as a separate non-superuser, non-owner database role. That changes the database setup and deployment, so it is the human maintainer's decision, and a plan of its own.
  4. **Design wrinkle:** one per-request `current_organization_id` doesn't fit the cross-organization queries (`ListMyOrganizations`, `ListMyInvitations`), which read several organizations' rows for one user. The real design needs a second, user-keyed condition (for example `OR user_id = current_setting('app.current_user_id', true)::uuid`), or those queries must be exempt.
  - Tracked as its own item in `docs/plans/0-production-readiness-roadmap.md`.

**Step 10 -- Dependency, docs, seed data, and roadmap/README checklist sync.**
- `docs/plans/0-production-readiness-roadmap.md` and `README.md` -- flip the multi-tenancy line from "planned" to done, in the style of this repo's other completed items.
- Add wiki documentation for the organizations concept, the membership/invite flow, and the two resource-ownership shapes.
- Extend `scripts/seed_db.py` with example organizations named after superhero teams (e.g. `Avengers`, `X-Men`, `Midnight Suns`), assigning several of the already-seeded `SEED_USERS` superheroes as members across more than one organization each, with a mix of `OWNER`/`ADMIN`/`MEMBER` roles and at least one still-pending (`accepted_at=None`) invitation -- giving the manual verification below ready-made fixture data instead of requiring fresh sign-ups and invitations by hand every time. Seed data is dev fixture data, not something to test-drive itself. **Update:** the organization seed data was moved forward and added alongside Step 6, as soon as the invitation routes existed (`docs/plans/agents.md` 1.3: seed data comes before the human check). It uses fixed ids so the human checks below can be copy-pasted, and Step 10 now only extends it for Steps 7 to 9.

---

## File Summary

| File | Purpose |
|---|---|
| `src/app/core/common/entities/organization.py` | `Organization` entity |
| `src/app/core/common/entities/organization_membership.py` | `OrganizationMembership` entity, `OrganizationRole` |
| `src/app/core/common/authorization/organization_ports.py` (`MembershipChecker`) | Shared port every organization-scoped `Permission` depends on |
| `src/app/core/common/authorization/organization_permissions.py` (`CanAccessOrganization`) | The one new `Permission`, reused by every future org-scoped feature |
| `src/app/core/common/authorization/current_organization_service.py` | Resolves "which organization, with what role" per request |
| `src/app/core/commands/{create,invite,accept,remove}_organization*.py` | The four organization-management commands |
| `src/app/core/queries/list_my_organizations.py`, `list_organization_members.py` | The two organization-management queries |
| `src/app/outbound/adapters/sqla_organization_repository.py` / `sqla_organization_reader.py` / `sqla_membership_checker.py` | Persistence adapters |
| `src/app/outbound/persistence_sqla/mappings/organization*.py` + migration | `organizations`/`organization_memberships` tables |
| `src/app/inbound/http/organizations/**` | The organization-management router group |
| `src/app/main/ioc/core.py` (+bindings) | Registers the new commands/queries/services on the existing `CoreProvider` |

## Verification Plan

- **`make check`** -- lint + `mypy --strict` + `lint-imports` (confirms `core.commands`/`core.queries` still don't cross-import, and the new `inbound/http/organizations/` package respects the existing layering contracts) + fast unit tests.
- **`make test-docker`** -- full integration suite, including every new organizations test alongside the untouched pre-existing suites.
- **Manual verification**, using real entrypoints and the seeded superhero fixture data from Step 10: confirm `ListMyOrganizations` for a seeded user returns exactly the organizations they're a member of, each with the correct role; confirm `ListOrganizationMembers` succeeds for a plain `MEMBER` of an organization (not just its `OWNER`/`ADMIN`), but returns `404` for a user with no membership in that organization at all; confirm a freshly seeded, not-yet-invited user gets `404` on every one of an organization's endpoints, while a `MEMBER` attempting an `ADMIN`-only action gets `403`; confirm an `ADMIN` can invite a new member as `MEMBER` but is refused with `CannotGrantOwnerRoleError` when attempting to invite someone as `OWNER`; confirm accepting the same invitation twice succeeds silently both times (idempotent) rather than erroring on the second call; confirm `GetOwnProfile` is entirely unaffected by any of the above -- proving personal and organization-scoped resources stay properly isolated concerns from each other, and across organizations.

---

## Human checks

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3), with copy-pasteable `curl` commands. They run mostly on data `scripts/seed_db.py` creates, and create only a little data by hand. Each step lands here as soon as its routes exist.

**A bug these checks found, now fixed.** Step 6 check 13 (re-inviting over an expired invitation) returned `500`:
- **Cause:** `AttributeError: 'OrganizationMembership' object has no attribute '_events'`. SQLAlchemy never calls `Entity.__init__` when it loads a row, so an entity read from the database had no `_events` list. Recording a domain event on it failed. Every earlier event had been recorded on a freshly built entity, so nothing hit this before.
- **Fix:** a SQLAlchemy `load` listener on the `Entity` base class, in `src/app/outbound/persistence_sqla/entity_load_events.py`, registered first in `map_tables()`. It gives every loaded entity an empty `_events` list. The domain layer (`base.py`) is unchanged.
- **Regression test:** `test_reinvite_over_an_expired_invitation_renews_the_row_loaded_from_the_database` in `tests/integration/with_infra/organizations/test_invitations.py`.

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`.
2. Start from a fresh, freshly seeded database. `db_pg` has no named volume, so `make down` discards the old database:
   ```shell
   make down
   make upd
   ```
   Re-run these two commands to reset the seeded state, because several checks below change it (accepting, declining).
3. Each user gets their own cookie file in `/tmp` (for example `/tmp/wade-wilson.cookies`), so you can switch between users without logging out. Every check starts by logging in each user it acts as, with the exact command and password. That's because a session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN` in `src/app/main/config/settings.py`), so a cookie from a few checks earlier may already have expired. An expired cookie gets `401 Not authenticated.`, and logging in again fixes it. A login answers `200` with the user's profile. Run every command in the same terminal, top to bottom.
4. No check takes its starting state on trust. Each one first runs its own read-only **Prove** command showing the state it relies on (who holds which role, which invitation is pending or expired, whose id is whose), even if an earlier check already showed it. A check that changes something ends with a command that shows the change. Each check's **Acts on:** line names every id its commands use. Those commands pipe the JSON through `python3 -m json.tool`, which just prints it one field per line.

### Seeded data (from `scripts/seed_db.py`)

The users and passwords are the existing `SEED_USERS`.

- **Avengers** (`a0000000-0000-4000-8000-000000000001`):
  - `tony-stark` (`ImIronMan#3000`) is OWNER, membership `c0000000-0000-4000-8000-000000000001`.
  - `natasha-romanoff` (`BlackWidow!!Red1`) is ADMIN, membership `c0000000-0000-4000-8000-000000000011`.
  - `peter-parker` (`SpideySense2024!`) is MEMBER, membership `c0000000-0000-4000-8000-000000000012`.
  - `bruce-wayne` (`IAmTheNight2024!!`) has a **pending** invitation, `b0000000-0000-4000-8000-000000000001`.
  - `diana-prince` (`AmazonWarrior$99`) has an **expired** invitation, `b0000000-0000-4000-8000-000000000002`.
- **X-Men** (`a0000000-0000-4000-8000-000000000002`):
  - `charles-xavier` (`Cerebro#Mutant42`) is OWNER.
  - `jean-grey` (`Phoenix19864202!`) is ADMIN.
  - `ororo-munroe` and `peter-parker` are MEMBERs.
  - `matt-murdock` (`Daredevil1!!`) has a **pending** invitation, `b0000000-0000-4000-8000-000000000003`.
- **Defenders** (`a0000000-0000-4000-8000-000000000003`):
  - `jessica-jones` is OWNER.
  - `luke-cage` is ADMIN.
  - `danny-rand` (`Iron$Fist_KunLun1!`) and `peter-parker` are MEMBERs.
- **Daily Bugle** (`a0000000-0000-4000-8000-000000000004`): `peter-parker` is OWNER. That puts him in all four organizations, for the list and pagination checks once the Step 7/8 list routes exist.
- `wade-wilson` (`MaximumEffort2024!!!`) belongs to **no** organization: he's the outsider.

### Who can do what (the rules these checks test)

Each organization has three roles, ranked from most to least powerful: **OWNER**, **ADMIN**, **MEMBER**. A higher role can do everything a lower one can.

- **MEMBER:** see the organization and its member list, and leave it.
- **ADMIN:** everything a MEMBER can, plus:
  - invite people, as MEMBER or ADMIN;
  - revoke pending invitations;
  - remove members and admins;
  - change a non-owner's role, except to OWNER.
- **OWNER:** everything an ADMIN can, plus invite or promote someone to OWNER, and remove or change another OWNER.
- **Every organization always keeps at least one OWNER,** so there is always someone who can manage it.
- **Outsiders get 404, not 403.** Anyone without an accepted membership gets `404 Organization not found.` for everything about that organization, and that includes pending invitees. A 403 would confirm the organization exists. A 404 gives nothing away, so organizations stay private from each other.
- **Anyone logged in can create an organization,** and becomes its OWNER.
- **Invitations:**
  - only the invitee can accept or decline one;
  - someone else's invitation looks like it doesn't exist (404);
  - they expire after 7 days (`ORGANIZATION_INVITATION_TTL_DAYS`).

What the status codes mean here:
- `401`: not logged in.
- `403`: logged in and a member, but your role is too low.
- `404`: it doesn't exist, or it isn't yours to see.
- `409`: the request conflicts with the current state (for example, already a member).
- `410`: it existed but has expired.
- `422`: the request itself is malformed (a bad id, an unknown role).

### 401 vs 404 vs 403: three callers, one request

These three checks send **the same request** (invite `danny-rand` to the Avengers) as three different callers, so the three refusals can be compared directly. Only the caller changes. The section relies on no other check, and changes nothing because all three requests are refused, so run it any time on freshly seeded data. Peter must still be an Avengers member, so not after Steps 7 and 8 check 14, where he leaves; check 3's Prove command shows it either way.

The three codes answer three different questions about the caller:
- `401`: the server doesn't know who you are (no cookie, or an expired one).
- `404`: it knows who you are, but you're not a member, so the organization "doesn't exist" for you.
- `403`: you are a member, but your role is too low.

1. **Nobody (no cookie): 401.**

   **Why:** every organization route needs a logged-in caller. With no cookie, the server stops before it looks at the organization at all, so it can't reveal anything about it.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`). The body names `danny-rand`, the user being invited.
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "danny-rand"}'
   ```
   Expect `401`. There's no `-b`, so no cookie is sent.

2. **Logged in, but not a member: 404.**

   **Why:** wade is logged in, so it's not a 401, but he has no membership in the Avengers. To him the organization "doesn't exist": a 403 would confirm it exists, while a 404 gives nothing away. This keeps organizations private from each other.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`). The body names `danny-rand`.

   Log in as `wade-wilson`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
   ```
   Expect `200`. **Prove** he belongs to no organization:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   ```
   Expect `"organizations": []` and `"total": 0`. Then send the same request as him:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "danny-rand"}'
   ```
   Expect `404`, with `Organization not found.`

3. **A member, but only a MEMBER: 403.**

   **Why:** peter is in the Avengers, so he may know it exists, and it's not a 404. But inviting needs at least ADMIN, and he's only a MEMBER, so he's refused for his role.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`). The body names `danny-rand`.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** his role in the Avengers:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect a `peter-parker` row with `"role": "member"`. Then send the same request as him:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "danny-rand"}'
   ```
   Expect `403`. Same URL and same body as checks 1 and 2; only who's asking changed.

### Step 6: invitations

1. **Not logged in: 401.**

   **Why:** every organization route needs a logged-in user. This command sends no cookie (there's no `-b`), so the server stops before it even looks at the organization.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "wade-wilson"}'
   ```
   Expect `401`.

2. **An outsider can't even see the organization: 404.**

   **Why:** wade isn't a member of the Avengers. To an outsider, the server answers as if the organization doesn't exist. A 403 would confirm that it exists, so it isn't used. This is what keeps organizations private from each other.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`). The body names `danny-rand`, the user wade tries to invite.

   Log in as `wade-wilson`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
   ```
   Expect `200`. **Prove** wade belongs to no organization, by listing his organizations:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   ```
   Expect `"organizations": []` and `"total": 0`. Then, as `wade-wilson`, try to invite someone to the Avengers:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "danny-rand"}'
   ```
   Expect a 404 body containing `Organization not found.`

3. **A MEMBER can't invite: 403.**

   **Why:** inviting needs at least ADMIN. peter is only a MEMBER of the Avengers, so he's refused. It's 403 and not 404 because he *is* a member: he may know the organization exists, he just isn't allowed to invite. The body `{"username": "wade-wilson"}` names who he's trying to invite. It has no `role`, so it would have been an invitation as MEMBER.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** peter is a MEMBER of the Avengers, not an ADMIN or OWNER, by listing the Avengers' members as him:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect the list to work: it's 200 and not 404, so he's in. Among the rows:
   - `"username": "peter-parker"` with `"role": "member"` and an `accepted_at` date;
   - `tony-stark` as `owner`;
   - `natasha-romanoff` as `admin`.

   Then, as `peter-parker`, try to invite wade:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "wade-wilson"}'
   ```
   Expect `403`.

4. **An ADMIN can't grant OWNER: 403.**

   **Why:** an ADMIN may invite, but only an OWNER can make someone an OWNER. Otherwise an admin could invite a friend as owner, and the two of them could then outrank or remove the real owner.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

   Log in as `natasha-romanoff`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
   ```
   Expect `200`. **Prove** natasha is an ADMIN of the Avengers, not an OWNER, by listing her organizations:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   ```
   Expect the Avengers (`a0000000-0000-4000-8000-000000000001`) with `"role": "admin"`. Two different counts appear here:
   - `"total": 1` is how many **organizations** natasha belongs to.
   - `"member_count": 3` is how many **people** the Avengers has: tony, natasha and peter. Pending and expired invitations aren't counted until they're accepted.

   Then, as `natasha-romanoff`, try to invite danny as an owner:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "danny-rand", "role": "owner"}'
   ```
   Expect `403`, with `Only an owner can grant the owner role.`

5. **An ADMIN can invite someone as ADMIN: 201.**

   **Why:** this is the allowed side of check 4: an ADMIN may invite at their own level or below. The invitation stays pending until danny accepts it, and expires after 7 days.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

   Log in as `natasha-romanoff`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
   ```
   Expect `200`. **Prove** natasha is an ADMIN of the Avengers, and that danny isn't in it yet, by listing the Avengers' members as her:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `natasha-romanoff` with `"role": "admin"`, and no `danny-rand` row. Then, as `natasha-romanoff`, invite danny to the Avengers as an admin:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "danny-rand", "role": "admin"}'
   ```
   Expect `201`, with a `membership_id` and an `expires_at` about 7 days from now. **Prove** the invitation exists, by listing the Avengers' members as natasha:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect a `danny-rand` row with `"role": "admin"`, `"accepted_at": null` (still pending) and the same `membership_id` as above.

6. **An existing member can't be invited again: 409.**

   **Why:** a user has at most one row per organization. peter is already an accepted member of the Avengers, so a second invitation conflicts with the current state. tony is the OWNER, so this isn't a permissions problem.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

   Log in as `tony-stark`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
   ```
   Expect `200`. **Prove** tony is the OWNER and peter is already an accepted member, by listing the Avengers' members as tony:
   ```shell
   curl -s -b /tmp/tony-stark.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `tony-stark` with `"role": "owner"`, and `peter-parker` with an `accepted_at` date. Then, as `tony-stark`, try to invite peter again:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "peter-parker"}'
   ```
   Expect `409`.

7. **An unknown username: 404.**

   **Why:** invitations only go to existing, active accounts, looked up by username. A missing account and a deactivated one get the same message, so the response never reveals which accounts are deactivated.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

   Log in as `tony-stark`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
   ```
   Expect `200`. **Prove** tony is the Avengers' OWNER, so the 404 below can only be about the username and not about his permissions. List his organizations:
   ```shell
   curl -s -b /tmp/tony-stark.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   ```
   Expect the Avengers with `"role": "owner"`. Then, as `tony-stark`, try to invite a username nobody has:
   ```shell
   curl -s -b /tmp/tony-stark.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "nobody-by-this-name"}'
   ```
   Expect a 404 body containing `No active user with that username.`

8. **A malformed organization id: 422.**

   **Why:** organization ids are UUIDs. FastAPI rejects anything else before any of our code runs, so a bad URL never reaches the database.

   **Acts on:** no real organization: `not-a-uuid` stands where an organization id belongs. Nothing needs proving here: the request is rejected before any role or row is looked up.

   Log in as `tony-stark`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
   ```
   Expect `200`. Then, as `tony-stark`, send the malformed id:
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/tony-stark.cookies -X POST \
     http://localhost:8000/api/v1/organizations/not-a-uuid/members/ \
     -H 'Content-Type: application/json' -d '{"username": "wade-wilson"}'
   ```
   Expect `422`.

9. **Someone else's invitation looks like it doesn't exist: 404.**

   **Why:** only the invitee can accept an invitation. danny isn't matt, so to him matt's invitation doesn't exist. It's the same privacy idea as check 2: he can't even confirm there's an invitation there to steal.

   **Acts on:** the X-Men (`a0000000-0000-4000-8000-000000000002`), and matt-murdock's pending invitation to the X-Men (`b0000000-0000-4000-8000-000000000003`).

   Log in as `danny-rand`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/danny-rand.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "danny-rand", "password": "Iron$Fist_KunLun1!"}'
   ```
   Expect `200`. **Prove** danny's own invitations don't include matt's, by listing danny's pending invitations:
   ```shell
   curl -s -b /tmp/danny-rand.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
   ```
   Expect no X-Men invitation, and no `b0000000-0000-4000-8000-000000000003`. The one invitation listed is danny's own: the Avengers invitation, as `admin`, that natasha sent in check 5. If you skipped check 5, the list is empty.

   Next, **prove** that `b0000000-0000-4000-8000-000000000003` really is matt's. Log in as `matt-murdock`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/matt-murdock.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "matt-murdock", "password": "Daredevil1!!"}'
   ```
   Expect `200`. Then list matt's pending invitations:
   ```shell
   curl -s -b /tmp/matt-murdock.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
   ```
   Expect one invitation: `"membership_id": "b0000000-0000-4000-8000-000000000003"`, `"organization_name": "X-Men"`. So the invitation exists; it just isn't danny's. Then, as `danny-rand`, try to accept matt's invitation:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/danny-rand.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/b0000000-0000-4000-8000-000000000003/accept/
   ```
   Expect `404`, with `Membership not found.`

10. **The invitee accepts a pending invitation: 204, and accepting twice is safe: 204 again.**

    **Why:** accepting turns bruce from a pending invitee into a MEMBER. Accepting twice being harmless (idempotent) means a double-click or a network retry never shows the user an error for something that already worked.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and bruce's pending invitation to it (`b0000000-0000-4000-8000-000000000001`).

    Log in as `bruce-wayne`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/bruce-wayne.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "bruce-wayne", "password": "IAmTheNight2024!!"}'
    ```
    Expect `200`. **Prove** bruce has a pending invitation to the Avengers, by listing his invitations:
    ```shell
    curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
    ```
    Expect `"membership_id": "b0000000-0000-4000-8000-000000000001"`, `"organization_name": "Avengers"`, `"role": "member"`. Then, as `bruce-wayne`, accept the same invitation twice:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/bruce-wayne.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/b0000000-0000-4000-8000-000000000001/accept/
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/bruce-wayne.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/b0000000-0000-4000-8000-000000000001/accept/
    ```
    Expect `204`, then `204`. **Prove** bruce is now a member, by listing his organizations:
    ```shell
    curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect the Avengers with `"role": "member"`. In Adminer (`http://localhost:8080`), the row now has `accepted_at` set and `expires_at` empty.

11. **Now a member, the invitee is refused for their role, not as an outsider: 403.**

    **Why:** this proves check 10 really made bruce a member. Before accepting, he'd have got 404 like any outsider; now he gets 403, "you're in, but your role is too low". As a MEMBER he still can't invite (check 3's rule).

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

    Log in as `bruce-wayne`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/bruce-wayne.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "bruce-wayne", "password": "IAmTheNight2024!!"}'
    ```
    Expect `200`. **Prove** bruce is now a MEMBER of the Avengers, by listing his organizations:
    ```shell
    curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect the Avengers with `"role": "member"`. Then, as `bruce-wayne`, try to invite wade to the Avengers:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/bruce-wayne.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
      -H 'Content-Type: application/json' -d '{"username": "wade-wilson"}'
    ```
    Expect `403`, not the 404 an outsider gets.

12. **An expired invitation can't be accepted: 410.**

    **Why:** invitations expire after 7 days, and diana's seeded one already has. 410 ("Gone") rather than 404 tells her the invitation did exist but is no longer valid, so she knows to ask for a new one.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and diana's expired invitation to it (`b0000000-0000-4000-8000-000000000002`).

    Log in as `diana-prince`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/diana-prince.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "diana-prince", "password": "AmazonWarrior$99"}'
    ```
    Expect `200`. Log in as `tony-stark` too, who will do the proving:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
    ```
    Expect `200`. **Prove** diana's invitation exists but has expired, by listing the Avengers' members as `tony-stark`:
    ```shell
    curl -s -b /tmp/tony-stark.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect a `diana-prince` row with `"membership_id": "b0000000-0000-4000-8000-000000000002"`, `"accepted_at": null`, and an `expires_at` date in the past. Then, as `diana-prince`, try to accept it:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/diana-prince.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/b0000000-0000-4000-8000-000000000002/accept/
    ```
    Expect `410`, with `This invitation has expired.`

13. **Re-inviting over an expired invitation renews that same row: 201, then accept gives 204.**

    **Why:** an expired invitation doesn't block a new one, unlike check 6's accepted member. Instead of adding a second row, the server renews the same row with a fresh expiry, which keeps the one-row-per-user-per-organization rule. tony is the OWNER, so he may invite.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and diana's expired invitation to it (`b0000000-0000-4000-8000-000000000002`).

    Log in as `tony-stark`, then as `diana-prince`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
    curl -s -w '\n%{http_code}\n' -c /tmp/diana-prince.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "diana-prince", "password": "AmazonWarrior$99"}'
    ```
    Expect `200` both times. **Prove** tony is the Avengers' OWNER and diana's invitation is still expired, by listing the Avengers' members as `tony-stark`:
    ```shell
    curl -s -b /tmp/tony-stark.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect `tony-stark` with `"role": "owner"`, and a `diana-prince` row with `"membership_id": "b0000000-0000-4000-8000-000000000002"`, `"accepted_at": null` and an `expires_at` in the past. Then, as `tony-stark`, re-invite diana to the Avengers:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
      -H 'Content-Type: application/json' -d '{"username": "diana-prince"}'
    ```
    Expect `201`, with `membership_id` equal to the **same** `b0000000-0000-4000-8000-000000000002` and a fresh `expires_at`. **Prove** diana can now see it, by listing her invitations:
    ```shell
    curl -s -b /tmp/diana-prince.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
    ```
    Expect `"membership_id": "b0000000-0000-4000-8000-000000000002"`, with an `expires_at` about 7 days from now. Then, as `diana-prince`, accept it:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/diana-prince.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/b0000000-0000-4000-8000-000000000002/accept/
    ```
    Expect `204`. **Prove** diana is now a member, by listing her organizations:
    ```shell
    curl -s -b /tmp/diana-prince.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect the Avengers with `"role": "member"`.

14. **The invitee declines: 204, and the invitation is gone: 404.**

    **Why:** an invitee can say no. Declining deletes the pending row, so it isn't left lying around. A second decline therefore finds nothing.

    **Acts on:** the X-Men (`a0000000-0000-4000-8000-000000000002`), and matt's pending invitation to it (`b0000000-0000-4000-8000-000000000003`).

    Log in as `matt-murdock`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/matt-murdock.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "matt-murdock", "password": "Daredevil1!!"}'
    ```
    Expect `200`. **Prove** matt has that pending invitation, by listing his invitations:
    ```shell
    curl -s -b /tmp/matt-murdock.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
    ```
    Expect `"membership_id": "b0000000-0000-4000-8000-000000000003"` and `"organization_name": "X-Men"`. Then, as `matt-murdock`, decline it twice:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/matt-murdock.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/b0000000-0000-4000-8000-000000000003/decline/
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/matt-murdock.cookies -X POST \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/b0000000-0000-4000-8000-000000000003/decline/
    ```
    Expect `204`, then `404`: the first call deleted the invitation. **Prove** it's gone, by listing matt's invitations again:
    ```shell
    curl -s -b /tmp/matt-murdock.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
    ```
    Expect `"invitations": []` and `"total": 0`.

15. **Create something by hand: a new organization and a new invitation.**

    **Why:** anyone logged in can create an organization, and becomes its OWNER straight away. So wade, the outsider everywhere else, is the owner here and may invite. This is the one check that builds its data from scratch instead of using the seed.

    **Acts on:** a new organization, "Mercs For Money", whose random id is saved in `$ORG_ID`.

    Log in as `wade-wilson`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
    ```
    Expect `200`. Then, as `wade-wilson`, create "Mercs For Money". The new organization's id is random, so this saves it in the shell variable `ORG_ID` and prints it:
    ```shell
    ORG_ID=$(curl -s -b /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/organizations/ \
      -H 'Content-Type: application/json' -d '{"name": "Mercs For Money"}' \
      | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')
    echo "$ORG_ID"
    ```
    Expect a UUID to be printed. A Python `KeyError` traceback means the create failed. **Prove** wade is its OWNER, by listing his organizations:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect one organization, `"name": "Mercs For Money"`, with the printed id, `"role": "owner"` and `"member_count": 1`. Then, still as `wade-wilson`, invite `luke-cage` to it:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST \
      "http://localhost:8000/api/v1/organizations/$ORG_ID/members/" \
      -H 'Content-Type: application/json' -d '{"username": "luke-cage"}'
    ```
    Expect `201`. **Prove** the invitation exists, by listing the new organization's members:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies "http://localhost:8000/api/v1/organizations/$ORG_ID/members/" | python3 -m json.tool
    ```
    Expect two rows: `wade-wilson` as `owner`, and `luke-cage` as `member` with `"accepted_at": null`.

### Steps 7 and 8: lists, removing, leaving and changing roles

The Step 6 checks above change the seeded rows, so start again from a freshly seeded database:
```shell
make down
make upd
```
Several checks below build on each other, so run them in order. The list checks come first because they change nothing.

1. **A user lists their own organizations, with their role and each member count.**

   **Why:** a user sees only the organizations they belong to, and their own role in each. `member_count` counts accepted members only: an invitation isn't a membership until it's accepted.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. Then, as `peter-parker`:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   ```
   Expect `total: 4`: Avengers, X-Men and Defenders as `member`, Daily Bugle as `owner`. Avengers' `member_count` is `3` (tony, natasha, peter): bruce's pending and diana's expired invitations don't count.

2. **The list is paginated.**

   **Why:** lists come in pages, so a user in many organizations never gets one huge response. `limit=2` asks for a page of two, sorted by name A to Z. `total` still reports all 4, so a client knows more pages exist.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. Then, as `peter-parker`, ask for the first page of two:
   ```shell
   curl -s -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/organizations/?limit=2&sorting_field=name&sorting_order=asc' | python3 -m json.tool
   ```
   Expect two organizations, Avengers then Daily Bugle, and `total: 4`.

3. **A plain MEMBER sees who else is in the organization, but only usernames.**

   **Why:** reading the member list needs only the lowest role, MEMBER. It includes pending and expired invitations, so members can see who has been asked. It shows usernames and roles, never email or phone number: members of one organization shouldn't get each other's private contact details.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`).

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. Then, as `peter-parker`, list the Avengers' members:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect 5 rows (`total: 5`) and `member_count: 3`. Note the `membership_id`s: tony's is `c0000000-0000-4000-8000-000000000001`, natasha's `c0000000-0000-4000-8000-000000000011` and peter's `c0000000-0000-4000-8000-000000000012`. Each later check lists them again before using them. bruce's row has `accepted_at: null` and a future `expires_at`; diana's has an `expires_at` in the past. No email or phone number anywhere.

4. **An outsider can't list the members: 404.**

   **Why:** Step 6 check 2's privacy rule, applied to reading. An outsider can't learn who belongs to an organization, or even that it exists.

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
   Expect `"total": 0`. Then, as `wade-wilson`, try to list the Avengers' members:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/
   ```
   Expect `404`, with `Organization not found.`

5. **An invitee sees their pending invitation, with the ids the accept route needs.**

   **Why:** an invitee needs a way to find their invitations without anyone sending them ids. This list gives the organization id and the `membership_id` that the accept and decline URLs are built from.

   Log in as `bruce-wayne`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/bruce-wayne.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "bruce-wayne", "password": "IAmTheNight2024!!"}'
   ```
   Expect `200`. Then, as `bruce-wayne`:
   ```shell
   curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
   ```
   Expect one invitation: `membership_id` `b0000000-0000-4000-8000-000000000001`, organization Avengers, invited by `tony-stark`, with an `expires_at`.

6. **An expired invitation isn't listed.**

   **Why:** an expired invitation can't be accepted (Step 6 check 12), so listing it would only offer a dead end.

   Log in as `diana-prince`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/diana-prince.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "diana-prince", "password": "AmazonWarrior$99"}'
   ```
   Expect `200`. Then, as `diana-prince`:
   ```shell
   curl -s -b /tmp/diana-prince.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
   ```
   Expect `total: 0`. Next, log in as `peter-parker`, who will do the proving:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** her invitation still exists and is only hidden from her own list, by listing the Avengers' (`a0000000-0000-4000-8000-000000000001`) members as `peter-parker`:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect a `diana-prince` row with `"membership_id": "b0000000-0000-4000-8000-000000000002"`, `"accepted_at": null` and an `expires_at` in the past.

7. **A MEMBER can't remove someone else: 403.**

   **Why:** removing *someone else* needs at least ADMIN. A MEMBER can remove only themselves, which is leaving (check 14). The last part of the URL is natasha's membership id, not her user id.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and natasha's membership in it (`c0000000-0000-4000-8000-000000000011`).

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** peter is a MEMBER and that `c0000000-0000-4000-8000-000000000011` is natasha's, by listing the Avengers' members as him:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `peter-parker` with `"role": "member"`, and `natasha-romanoff` with `"role": "admin"` and `"membership_id": "c0000000-0000-4000-8000-000000000011"`. Then, as `peter-parker`, try to remove natasha from the Avengers:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X DELETE \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000011/
   ```
   Expect `403`. **Prove** nothing changed, by listing the Avengers' members again:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `natasha-romanoff` still there, as `admin`.

8. **An ADMIN can't remove an OWNER: 403.**

   **Why:** an ADMIN can remove members and other admins, but not an OWNER. Otherwise an admin could take over the organization by removing its owner.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and tony's membership in it (`c0000000-0000-4000-8000-000000000001`).

   Log in as `natasha-romanoff`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
   ```
   Expect `200`. **Prove** natasha is an ADMIN, not an OWNER, and that `c0000000-0000-4000-8000-000000000001` is tony's, by listing the Avengers' members as her:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `natasha-romanoff` with `"role": "admin"`, and `tony-stark` with `"role": "owner"` and `"membership_id": "c0000000-0000-4000-8000-000000000001"`. Then, as `natasha-romanoff`, try to remove tony from the Avengers:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X DELETE \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000001/
   ```
   Expect `403`, with `Only an owner can remove or change another owner.`

9. **An ADMIN can't grant OWNER: 403.**

   **Why:** Step 6 check 4's rule, applied to changing an existing member's role instead of inviting: only an OWNER can create another OWNER.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and peter's membership in it (`c0000000-0000-4000-8000-000000000012`).

   Log in as `natasha-romanoff`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
   ```
   Expect `200`. **Prove** natasha is still an ADMIN and that `c0000000-0000-4000-8000-000000000012` is peter's, by listing the Avengers' members as her:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `natasha-romanoff` with `"role": "admin"`, and `peter-parker` with `"role": "member"` and `"membership_id": "c0000000-0000-4000-8000-000000000012"`. Then, as `natasha-romanoff`, try to promote peter to owner:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X PATCH \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000012/ \
     -H 'Content-Type: application/json' -d '{"role": "owner"}'
   ```
   Expect `403`, with `Only an owner can grant the owner role.` **Prove** peter is still a member, by listing the Avengers' members as natasha:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `peter-parker` still `member`, and `tony-stark` still there as `owner` (check 8 didn't remove him either).

10. **The last owner can neither leave nor demote themselves: 409.**

    **Why:** every organization must always keep at least one OWNER, or no one could ever manage it again. tony is the Avengers' only owner, so both leaving and demoting himself are refused. It's 409, not 403: tony has every permission, and it's the organization's current state (one owner) that blocks it. Check 12 shows the right way to do it.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and tony's own membership in it (`c0000000-0000-4000-8000-000000000001`).

    Log in as `tony-stark`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
    ```
    Expect `200`. **Prove** tony is the Avengers' only OWNER, by listing the members as him:
    ```shell
    curl -s -b /tmp/tony-stark.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect exactly one row with `"role": "owner"`: `tony-stark`, `membership_id` `c0000000-0000-4000-8000-000000000001`. Then, as `tony-stark`, try to leave, then try to demote himself:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X DELETE \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000001/
    curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000001/ \
      -H 'Content-Type: application/json' -d '{"role": "admin"}'
    ```
    Expect `409` both times, with `The organization's last owner cannot be removed or demoted.`

11. **An unknown role is rejected: 422.**

    **Why:** a role must be `owner`, `admin` or `member`. Anything else is rejected before any of our code runs.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and peter's membership in it (`c0000000-0000-4000-8000-000000000012`). Nothing needs proving here: the made-up role is rejected before any role or row is looked up.

    Log in as `tony-stark`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
    ```
    Expect `200`. Then, as `tony-stark`, try to give peter a made-up role:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/tony-stark.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000012/ \
      -H 'Content-Type: application/json' -d '{"role": "emperor"}'
    ```
    Expect `422`.

12. **Ownership is transferred by promoting someone else first: 204, then the old owner can leave: 204.**

    **Why:** this is the way out of check 10. Once natasha is promoted there are two owners, so tony is no longer the last one and may leave. He's an OWNER, so he's allowed to grant OWNER.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), natasha's membership in it (`c0000000-0000-4000-8000-000000000011`), and tony's own (`c0000000-0000-4000-8000-000000000001`).

    Log in as `tony-stark`, and as `peter-parker`, who checks the result:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200` both times. **Prove** tony is still the only OWNER, and which membership is whose, by listing the Avengers' members as `tony-stark`:
    ```shell
    curl -s -b /tmp/tony-stark.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect `tony-stark` as the only `owner` (`c0000000-0000-4000-8000-000000000001`), and `natasha-romanoff` as `admin` (`c0000000-0000-4000-8000-000000000011`). Then, as `tony-stark`, promote natasha to owner, then leave the Avengers:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/tony-stark.cookies -X PATCH \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000011/ \
      -H 'Content-Type: application/json' -d '{"role": "owner"}'
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/tony-stark.cookies -X DELETE \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000001/
    ```
    Expect `204` both times. Then, as `peter-parker`, list the Avengers' members again:
    ```shell
    curl -s -b /tmp/peter-parker.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect `total: 4`: tony is gone, and natasha is now `owner`.

13. **An ADMIN or OWNER revokes a pending invitation: 204.**

    **Why:** revoking uses the same DELETE route as removing a member, pointed at the invitation's id, so it needs the same role: ADMIN or higher. An invitation sent by mistake can be withdrawn before it's accepted. bruce's own invitation list then confirms it's gone.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and bruce's pending invitation to it (`b0000000-0000-4000-8000-000000000001`).

    Log in as `natasha-romanoff`, and as `bruce-wayne`, who checks the result:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
    curl -s -w '\n%{http_code}\n' -c /tmp/bruce-wayne.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "bruce-wayne", "password": "IAmTheNight2024!!"}'
    ```
    Expect `200` both times. **Prove** natasha is now an OWNER and bruce's invitation is pending, by listing the Avengers' members as `natasha-romanoff`:
    ```shell
    curl -s -b /tmp/natasha-romanoff.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect `natasha-romanoff` with `"role": "owner"`, and a `bruce-wayne` row with `"membership_id": "b0000000-0000-4000-8000-000000000001"` and `"accepted_at": null`. Then, as `natasha-romanoff`, revoke bruce's invitation:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X DELETE \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/b0000000-0000-4000-8000-000000000001/
    ```
    Expect `204`. Then, as `bruce-wayne`, list his invitations again:
    ```shell
    curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
    ```
    Expect `total: 0`.

14. **Any member can leave: 204.**

    **Why:** leaving is removing yourself, which needs no higher role. Nobody can be kept in an organization against their will. The one exception is the last owner (check 10).

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and peter's own membership in it (`c0000000-0000-4000-8000-000000000012`).

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. **Prove** peter is a MEMBER and that `c0000000-0000-4000-8000-000000000012` is his, by listing the Avengers' members as him:
    ```shell
    curl -s -b /tmp/peter-parker.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    ```
    Expect `peter-parker` with `"role": "member"` and `"membership_id": "c0000000-0000-4000-8000-000000000012"`. Then, as `peter-parker`, leave the Avengers:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/peter-parker.cookies -X DELETE \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/c0000000-0000-4000-8000-000000000012/
    ```
    Expect `204`. Then, as `peter-parker`, list his organizations again:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `total: 3`, with no Avengers.

15. **An ADMIN can leave too: 204, and is then an outsider: 404.**

    **Why:** leaving needs no particular role, so an ADMIN leaves the same way a MEMBER does (check 14). Only the last OWNER is blocked (check 10). Once she has left, she has no membership, so the organization looks like it doesn't exist to her, as to any outsider.

    **Acts on:** the X-Men (`a0000000-0000-4000-8000-000000000002`), and jean-grey's own membership in it. Its id isn't a fixed seed id, so it's saved in `$JEAN_MEMBERSHIP_ID`.

    Log in as `jean-grey`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
    ```
    Expect `200`. **Prove** jean is an ADMIN of the X-Men, by listing its members as her:
    ```shell
    curl -s -b /tmp/jean-grey.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/ | python3 -m json.tool
    ```
    Expect a `jean-grey` row with `"role": "admin"` and an `accepted_at` date, and `charles-xavier` as `owner`. Save jean's membership id from the same list:
    ```shell
    JEAN_MEMBERSHIP_ID=$(curl -s -b /tmp/jean-grey.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/ \
      | python3 -c 'import sys, json; print(next(m["membership_id"] for m in json.load(sys.stdin)["members"] if m["username"] == "jean-grey"))')
    echo "$JEAN_MEMBERSHIP_ID"
    ```
    Expect a UUID. Then, as `jean-grey`, leave the X-Men:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/jean-grey.cookies -X DELETE \
      "http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/$JEAN_MEMBERSHIP_ID/"
    ```
    Expect `204`. **Prove** she's gone and is now an outsider, by trying to list the X-Men's members as her again:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/jean-grey.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000002/members/
    ```
    Expect `404`, with `Organization not found.`, the same as wade gets.

### Invitation email (Step 6b)

A self-contained check, relying on no other check. The invitation email goes to the invitee **account's** email address, not to anything in the invite request, so the check signs up a throwaway account with your own email, then invites it.

**Where the email goes.** With the default `EMAIL_USE_CONSOLE=true`, nothing is actually sent: the worker prints the email to its log. To receive it in your inbox instead, set these in `.secrets`, with your SMTP provider's details:
```
EMAIL_USE_CONSOLE=false
EMAIL_SMTP_HOST=smtp-relay.brevo.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=your-smtp-login
EMAIL_SMTP_PASSWORD=your-smtp-password
EMAIL_FROM_EMAIL=an-address-your-provider-lets-you-send-from
```
Then restart, so the worker picks them up. This also re-seeds the database:
```shell
make down
make upd
```

1. **Inviting someone emails them: 201, then the worker sends "You're invited to join Avengers".**

   **Why:** an invitee should hear about an invitation without having to go looking. Inviting records an `OrganizationInvitationCreatedEvent`, and `SendOrganizationInvitationEmail` handles it in the background: its outbox row is staged in the same transaction as the invitation, so the invitation and its email can't get out of step. The worker's drain loop sends it within a few seconds (`CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS`, default 3).

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and a new account `invite-tester` with your email, in `$MY_EMAIL`.

   Put your email in a shell variable. This is the only line to edit:
   ```shell
   MY_EMAIL='replace-with-your-email@example.com'
   ```
   Sign up `invite-tester` with that email. The username, password and phone number are fixed test values that pass the validation rules:
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "invite-tester", "password": "InviteTester2024!", "email": "'"$MY_EMAIL"'", "phone_number": "27821000099"}'
   ```
   The JSON is in single quotes, because inside double quotes bash would treat the password's `!` as history expansion (`event not found`). The `'"$MY_EMAIL"'` part closes the single quotes, inserts your email, and reopens them. Expect `201`, with `"username": "invite-tester"` and your email. Signing up also sends a **welcome email** to the same address, so you'll get two emails in all. (Usernames and phone numbers must be unique: to run this check again, reset first with `make down` and `make upd`.)

   Log in as `tony-stark`, the Avengers' owner:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/tony-stark.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000"}'
   ```
   Expect `200`. **Prove** tony is the owner and invite-tester isn't in the Avengers yet, by listing its members:
   ```shell
   curl -s -b /tmp/tony-stark.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   ```
   Expect `tony-stark` with `"role": "owner"`, and no `invite-tester` row. Then invite `invite-tester` to the Avengers:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/tony-stark.cookies -X POST \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ \
     -H 'Content-Type: application/json' -d '{"username": "invite-tester"}'
   ```
   Expect `201`, with a `membership_id` and an `expires_at` 7 days out.

   **Prove** the email went out. Set the Compose project name the way the Makefile does (`APP_SERVICE_NAME`, last value wins, else the folder name), then search the worker's log, which prints the matches and exits:
   ```shell
   PROJECT=$(grep -h '^APP_SERVICE_NAME=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2)
   PROJECT=${PROJECT:-$(basename "$PWD")}
   echo "$PROJECT"
   docker compose -p "$PROJECT" logs --no-log-prefix worker | grep -i 'invitation email'
   ```
   Expect `Sending organization invitation email to` and `Organization invitation email sent to`, each followed by your email. With SMTP set up, the email arrives with the subject "You're invited to join Avengers", saying tony-stark invited you as member and when the invitation expires. In console mode, the full email is in the worker log: `make logs service=worker tail=100`, then Ctrl-C.
