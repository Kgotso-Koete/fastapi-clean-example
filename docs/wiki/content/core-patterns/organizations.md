# Organizations (Multi-Tenancy)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/core/common/entities/organization.py`](../../../../src/app/core/common/entities/organization.py) — `Organization`: a tenant boundary, deliberately minimal (a name, a mandatory description, and who created it)
    - [`src/app/core/common/entities/organization_membership.py`](../../../../src/app/core/common/entities/organization_membership.py) — `OrganizationMembership` and `OrganizationRole` (`OWNER`/`ADMIN`/`MEMBER`): one row per (organization, user), pending or accepted
    - [`src/app/core/common/authorization/organization_ports.py`](../../../../src/app/core/common/authorization/organization_ports.py) — `MembershipChecker`, the one shared port every organization-scoped check depends on
    - [`src/app/core/common/authorization/organization_permissions.py`](../../../../src/app/core/common/authorization/organization_permissions.py) — `ORGANIZATION_ROLE_HIERARCHY` and `CanAccessOrganization`
    - [`src/app/core/common/authorization/current_organization_service.py`](../../../../src/app/core/common/authorization/current_organization_service.py) — `CurrentOrganizationService.require_role()`: "is the caller at least this role in this organization?"
    - [`src/app/core/commands/`](../../../../src/app/core/commands/) — `create_organization.py`, `update_organization.py`, `delete_organization.py`, `invite_organization_member.py`, `accept_organization_invitation.py`, `decline_organization_invitation.py`, `remove_organization_member.py`, `change_organization_member_role.py`, `organization_exceptions.py`
    - [`src/app/core/queries/`](../../../../src/app/core/queries/) — `list_my_organizations.py`, `list_organization_members.py`, `list_my_invitations.py`
    - [`src/app/core/common/events/organization_invitation_created.py`](../../../../src/app/core/common/events/organization_invitation_created.py) / [`handlers/send_organization_invitation_email.py`](../../../../src/app/core/common/events/handlers/send_organization_invitation_email.py) — the invitation email, as a background domain event
    - [`src/app/outbound/adapters/`](../../../../src/app/outbound/adapters/) — `sqla_organization_repository.py`, `sqla_organization_reader.py`, `sqla_membership_checker.py`
    - [`src/app/outbound/persistence_sqla/entity_load_events.py`](../../../../src/app/outbound/persistence_sqla/entity_load_events.py) — gives entities loaded from the database their domain-event list back (see below)
    - [`src/app/inbound/http/organizations/`](../../../../src/app/inbound/http/organizations/) — every organization route
    - [`docs/plans/9-organizations.md`](../../../../docs/plans/9-organizations.md) — the full implementation plan, design rationale, and copy-pasteable human checks

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this is

A second bounded context next to Identity, so the template supports two kinds of resource side by side:

- **Personal resources**, owned by one `user_id`. Nothing new is needed for these: `ApiKey` and `GetOwnProfile` are this shape already.
- **Organization-scoped resources**, owned by an `organization_id`, reachable only by that organization's members, with an organization role deciding what each member may do.

It was added as a building block on top of Identity, not by changing it. `User` knows nothing about organizations; `OrganizationMembership.user_id` is a plain reference, the same kind `ApiKey.user_id` is. A fork that never needs organizations can leave this context out entirely.

A user can belong to many organizations, through a membership row (`user_id`, `organization_id`, `role`), rather than one `tenant_id` column on the user. Two of the three reference SaaS codebases studied in the plan use this same join-entity shape.

## Two independent role axes

A platform role and an organization role are unrelated facts about the same account:

- `UserRole` (`super_admin`/`admin`/`user`) answers "what can this account do to the platform": managing users. See [Authorization & RBAC](authorization-rbac.md).
- `OrganizationRole` (`owner`/`admin`/`member`) answers "what can this account do inside *this one* organization". A platform `user` can be an organization `owner`, and a platform `super_admin` an organization `member`.

## Who can do what

Roles rank `OWNER` > `ADMIN` > `MEMBER`, and a higher role can do everything a lower one can (`ORGANIZATION_ROLE_HIERARCHY`).

- **MEMBER:** see the organization and its member list, and leave it.
- **ADMIN:** also edit the organization's name and description, invite people (as `MEMBER` or `ADMIN`), revoke pending invitations, remove members and admins, and change a non-owner's role.
- **OWNER:** also invite or promote someone to `OWNER`, remove or change another owner, and delete the organization.
- **Every organization always keeps at least one accepted, active OWNER.** Removing, demoting or leaving as the last owner fails with `LastOwnerError` (409). An owner whose account a platform admin has deactivated doesn't count, since they can't log in to run it. Ownership is handed over by promoting someone else first.
- **Anyone logged in can create an organization,** and becomes its owner in the same transaction: an organization can never exist without one.
- **Every organization explains itself.** The description is mandatory: trimmed, 1 to 1000 characters, line breaks and tabs allowed, other control characters rejected (the `Description` value object). It can be changed but never cleared. It's shown in the member's organization list and, as `organization_description`, in an invitee's invitation list, so they know what they're being asked to join.
- **Deleting an organization deletes everything in it.** `organization_memberships.organization_id` is `ON DELETE CASCADE`, so the database removes every membership and invitation in the same statement.

## Outsiders get 404, not 403

Anyone without an *accepted* membership, including someone with only a pending invitation, gets `404 Organization not found.` on every route scoped to that organization. A 403 would confirm the organization exists; a 404 gives nothing away, so organizations stay private from each other. The three refusals mean three different things:

- `401`: not logged in.
- `404`: logged in, but not a member.
- `403`: a member, but the role is too low.

The same idea covers invitations: someone else's invitation looks like it doesn't exist (`MembershipNotFoundError`, 404).

## How a request is authorized

`Permission.is_satisfied_by()` is synchronous everywhere in this codebase, but looking up a membership needs the database. So `CurrentOrganizationService.require_role()` looks the role up *first*, through the `MembershipChecker` port, then hands the resolved role to `CanAccessOrganization`:

!!! figure "require_role(): resolve the role, then authorize"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "useMaxWidth": false}}}%%
    flowchart TB
        uc["A use case, e.g. InviteOrganizationMember"] -->|"require_role(org_id, ADMIN)"| cos["CurrentOrganizationService"]
        cos -->|"who is calling?"| cus["CurrentUserService"]
        cos -->|"get_role(user_id, org_id) -- async, database"| mc["MembershipChecker port<br/>(SqlaMembershipChecker)"]
        mc -->|"role, or None if no accepted membership"| cos
        cos -->|"OrganizationAccessContext(member_role, minimum_role)"| perm["CanAccessOrganization<br/>(synchronous)"]
        perm -->|"None"| nf["OrganizationNotFoundError -> 404"]
        perm -->|"role too low"| az["AuthorizationError -> 403"]
        perm -->|"allowed"| ok["use case continues"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

`MembershipChecker` lives in `core/common/authorization/`, next to `AuthzUserFinder`, not inside any one feature. Every future organization-scoped feature reuses the same port and permission, instead of redefining "is this user a member".

## Memberships and invitations: one row, three states

An invitation and a membership are the same row. `accepted_at` is null while it's pending; `expires_at` is set while it's pending and cleared on acceptance, and the entity enforces that exactly one of the two is set.

!!! figure "An OrganizationMembership row's lifecycle"
    ```mermaid
    stateDiagram-v2
        [*] --> Pending: invite (expires_at = now + ORGANIZATION_INVITATION_TTL_DAYS)
        Pending --> Accepted: invitee accepts (accepting twice is harmless)
        Pending --> Expired: expires_at passes
        Expired --> Pending: re-invite renews the same row
        Pending --> [*]: declined, or revoked by an ADMIN/OWNER
        Expired --> [*]: declined
        Accepted --> [*]: removed, or leaves
    ```

- **One row per (organization, user),** enforced by a unique constraint. Inviting someone who already has a live row (a membership, or a pending invitation that hasn't expired) is `MembershipAlreadyExistsError` (409). Re-inviting over an *expired* invitation renews that same row instead of adding a second one.
- **Invitations expire** after `ORGANIZATION_INVITATION_TTL_DAYS` (default 7). Accepting an expired invitation is `InvitationExpiredError` (410 Gone): it existed, but is no longer valid.
- **Invitations go only to existing, active accounts,** found by username. A missing account and a deactivated one get the same `UnknownInviteeError` (404), so the response never reveals which accounts are deactivated.

## The invitation email

Inviting (or renewing an expired invitation) records an `OrganizationInvitationCreatedEvent` on the membership. `SendOrganizationInvitationEmail` handles it in `"background"` mode, so its outbox row is staged in the same transaction as the invitation and delivered by the worker, exactly like the welcome email. See [Domain Events & the Transactional Outbox](domain-events-outbox.md).

Renewing an invitation was the first time this codebase recorded an event on an entity *loaded from the database* rather than freshly built. That exposed a gap: SQLAlchemy never calls `__init__` when it loads a row, so a loaded entity had no `_events` list and recording an event failed. `entity_load_events.py` fixes this in the persistence layer with a SQLAlchemy `load` listener on the `Entity` base class, so the domain layer stays unaware of SQLAlchemy. It covers every mapped entity, not just memberships.

## Endpoints

All under the private app, cookie-authenticated. The two lists `GET /api/v1/organizations/` and `GET .../{organization_id}/members/` are also on the public API, read-only, at `/public/v1/organizations/` with an `X-API-Key` (see [Public API](public-api.md#endpoints)); every write, and the invitation list, stays here.

| Method + path | Interactor | Minimum role |
|---|---|---|
| `POST /api/v1/organizations/` | `CreateOrganization` | any logged-in user; `name` and `description` both required |
| `GET /api/v1/organizations/` | `ListMyOrganizations` | none: only the caller's own accepted organizations, with their description, role and `member_count` |
| `GET /api/v1/organizations/invitations/` | `ListMyInvitations` | none: the caller's own pending, unexpired invitations, with the organization's name and description |
| `PATCH /api/v1/organizations/{organization_id}/` | `UpdateOrganization` | ADMIN; a partial update of `name` and/or `description`, returning `200` with both |
| `DELETE /api/v1/organizations/{organization_id}/` | `DeleteOrganization` | OWNER |
| `POST /api/v1/organizations/{organization_id}/members/` | `InviteOrganizationMember` | ADMIN (OWNER to invite as owner) |
| `GET /api/v1/organizations/{organization_id}/members/` | `ListOrganizationMembers` | MEMBER; usernames and roles only, never email or phone |
| `POST /api/v1/organizations/{organization_id}/members/{membership_id}/accept/` | `AcceptOrganizationInvitation` | the invitee |
| `POST /api/v1/organizations/{organization_id}/members/{membership_id}/decline/` | `DeclineOrganizationInvitation` | the invitee |
| `PATCH /api/v1/organizations/{organization_id}/members/{membership_id}/` | `ChangeOrganizationMemberRole` | ADMIN (OWNER for owner changes) |
| `DELETE /api/v1/organizations/{organization_id}/members/{membership_id}/` | `RemoveOrganizationMember` | MEMBER to leave, ADMIN to remove someone or revoke an invitation, OWNER to remove an owner |

`member_count` counts accepted memberships only, while a member list's `total` counts every listed row, pending invitations included. The two differ on purpose.

## Not yet: Row-Level Security

Scoping is enforced in the application layer today: every query filters by organization, and every organization-scoped use case calls `require_role()`. Postgres Row-Level Security, as a second layer so a forgotten filter can't leak another organization's rows, was proven feasible by a spike (`tests/integration/with_infra/organizations/test_rls_spike.py`) but isn't enforced yet. Two things block it: superusers bypass RLS, so the app must first connect as a separate non-superuser role, and the cross-organization queries need a user-keyed condition. It has its own plan, `docs/plans/14-row-level-security.md`, sequenced before search and file storage.

## Testing

- Unit tests with fakes: [`tests/unit/core/commands/organizations/`](../../../../tests/unit/core/commands/organizations/), plus the queries, permissions, entities and events under `tests/unit/core/`.
- Integration tests through the real HTTP stack, DI container and Postgres: [`tests/integration/with_infra/organizations/`](../../../../tests/integration/with_infra/organizations/), including the invitation-email outbox and worker tests, and the regression test for the entity-load fix.
- Development seed data (`scripts/seed_db.py`, with `SEED_DB_WITH_TEST_DATA=true`): four superhero organizations with fixed ids, every role, and pending and expired invitations, so `docs/plans/9-organizations.md`'s human checks can be pasted as written.

## Where to go next

- [Authorization & RBAC](authorization-rbac.md) — the platform-role side, and the `Permission`/`authorize()` shape `CanAccessOrganization` follows.
- [Domain Events & the Transactional Outbox](domain-events-outbox.md) — how the invitation email is delivered.
- [Public API (Server-to-Server Clients)](public-api.md) — the API-key entrypoint, which serves the two organization lists read-only.
- `docs/plans/9-organizations.md` — the complete implementation record and human checks.
