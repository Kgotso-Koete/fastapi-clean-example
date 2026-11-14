"""
Organizations' development data (docs/plans/16-modular-monolith.md, Step 4g):
the organizations, memberships and invitations scripts/seed_db.py adds after
base's own users and API keys, when SEED_DB_WITH_TEST_DATA=true. main/module.py
lists seed_organizations() in SEEDS, so deregistering Organizations drops this
data with it.

Moved unchanged from scripts/seed_db.py, apart from seed_organizations() at the
bottom, which holds the lines seed_db.py's main() ran for organizations.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.common.entities.types_ import UserId
from app.base.core.common.value_objects.description import Description
from app.base.core.common.value_objects.utc_datetime import UtcDatetime
from app.modules.organizations.core.common.entities.organization import Organization, OrganizationId
from app.modules.organizations.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.modules.organizations.core.common.factories.organization_membership_id_factory import (
    create_organization_membership_id,
)
from app.modules.organizations.core.common.value_objects.organization_name import OrganizationName
from app.modules.organizations.main.config.settings import OrganizationSettings
from app.modules.organizations.outbound.persistence_sqla.mappings.organization_membership import (
    organization_memberships_table,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SeedOrganization:
    # A FIXED id (not generated), so the human checks documented in
    # docs/plans/9-organizations.md can use copy-pasteable curl commands.
    id: UUID
    name: str
    # Mandatory, as for every organization: what invitees read about it.
    description: str
    owner_username: str  # must match a SeedUser.username in scripts/seed_db.py
    # The owner's own membership row, also fixed, so the Step 7 human checks
    # (the last owner can't leave or be demoted) can name it in a curl.
    owner_membership_id: UUID


@dataclass(frozen=True, slots=True)
class SeedMembership:
    organization_id: UUID  # must match a SeedOrganization.id above
    username: str  # must match a SeedUser.username in scripts/seed_db.py
    role: OrganizationRole
    # "accepted" = a real member; "pending" = a live invitation;
    # "expired" = an invitation whose expiry is already in the past.
    state: Literal["accepted", "pending", "expired"]
    # Fixed for rows the human checks act on by id (accept/decline an
    # invitation, remove a member, change a role); None means "generate one"
    # (nobody needs to type it).
    id: UUID | None = None


SEED_ORG_AVENGERS = UUID("a0000000-0000-4000-8000-000000000001")
SEED_ORG_X_MEN = UUID("a0000000-0000-4000-8000-000000000002")
SEED_ORG_DEFENDERS = UUID("a0000000-0000-4000-8000-000000000003")
SEED_ORG_DAILY_BUGLE = UUID("a0000000-0000-4000-8000-000000000004")

# Each owner becomes that organization's accepted OWNER automatically (as
# CreateOrganization does), so owners are not repeated in SEED_MEMBERSHIPS.
SEED_ORGANIZATIONS: list[SeedOrganization] = [
    SeedOrganization(
        SEED_ORG_AVENGERS,
        "Avengers",
        "Earth's mightiest heroes.",
        "tony-stark",
        UUID("c0000000-0000-4000-8000-000000000001"),
    ),
    SeedOrganization(
        SEED_ORG_X_MEN,
        "X-Men",
        "Mutants sworn to protect a world that fears and hates them.",
        "charles-xavier",
        UUID("c0000000-0000-4000-8000-000000000002"),
    ),
    SeedOrganization(
        SEED_ORG_DEFENDERS,
        "Defenders",
        "Street-level heroes keeping Hell's Kitchen safe.",
        "jessica-jones",
        UUID("c0000000-0000-4000-8000-000000000003"),
    ),
    SeedOrganization(
        SEED_ORG_DAILY_BUGLE,
        "Daily Bugle",
        "New York's finest tabloid newspaper.",
        "peter-parker",
        UUID("c0000000-0000-4000-8000-000000000004"),
    ),
]

# Covers every state the invitation routes can reach:
# - owners, admins and members in every organization
# - a pending invitation (bruce-wayne, matt-murdock) and an expired one (diana-prince)
# - peter-parker in all four organizations (owner of one), for list/pagination checks
# - wade-wilson deliberately in none: the outsider for 404 checks
SEED_MEMBERSHIPS: list[SeedMembership] = [
    SeedMembership(
        SEED_ORG_AVENGERS,
        "natasha-romanoff",
        OrganizationRole.ADMIN,
        "accepted",
        id=UUID("c0000000-0000-4000-8000-000000000011"),
    ),
    SeedMembership(
        SEED_ORG_AVENGERS,
        "peter-parker",
        OrganizationRole.MEMBER,
        "accepted",
        id=UUID("c0000000-0000-4000-8000-000000000012"),
    ),
    SeedMembership(
        SEED_ORG_AVENGERS,
        "bruce-wayne",
        OrganizationRole.MEMBER,
        "pending",
        id=UUID("b0000000-0000-4000-8000-000000000001"),
    ),
    SeedMembership(
        SEED_ORG_AVENGERS,
        "diana-prince",
        OrganizationRole.MEMBER,
        "expired",
        id=UUID("b0000000-0000-4000-8000-000000000002"),
    ),
    SeedMembership(SEED_ORG_X_MEN, "jean-grey", OrganizationRole.ADMIN, "accepted"),
    SeedMembership(SEED_ORG_X_MEN, "ororo-munroe", OrganizationRole.MEMBER, "accepted"),
    SeedMembership(SEED_ORG_X_MEN, "peter-parker", OrganizationRole.MEMBER, "accepted"),
    SeedMembership(
        SEED_ORG_X_MEN,
        "matt-murdock",
        OrganizationRole.MEMBER,
        "pending",
        id=UUID("b0000000-0000-4000-8000-000000000003"),
    ),
    SeedMembership(SEED_ORG_DEFENDERS, "luke-cage", OrganizationRole.ADMIN, "accepted"),
    SeedMembership(SEED_ORG_DEFENDERS, "danny-rand", OrganizationRole.MEMBER, "accepted"),
    SeedMembership(SEED_ORG_DEFENDERS, "peter-parker", OrganizationRole.MEMBER, "accepted"),
]


async def _seed_organization(
    session: AsyncSession,
    owner_id: UserId,
    seed: SeedOrganization,
) -> None:
    # Skipped if already seeded (the script runs on every `make upd`).
    if await session.get(Organization, OrganizationId(seed.id)) is not None:
        logger.info("Seed organization %s already exists, skipping.", seed.name)
        return
    # Same two rows CreateOrganization writes: the organization, plus its
    # creator as an already-accepted OWNER.
    now = UtcDatetime(datetime.now(UTC))
    session.add(
        Organization(
            id_=OrganizationId(seed.id),
            name=OrganizationName(seed.name),
            description=Description(seed.description),
            created_by_user_id=owner_id,
            created_at=now,
        )
    )
    session.add(
        OrganizationMembership(
            id_=OrganizationMembershipId(seed.owner_membership_id),
            organization_id=OrganizationId(seed.id),
            user_id=owner_id,
            role=OrganizationRole.OWNER,
            invited_by_user_id=owner_id,
            created_at=now,
            accepted_at=now,
            expires_at=None,
        )
    )
    logger.info("Seeded organization %s (%s), owned by %s", seed.name, seed.id, seed.owner_username)


async def _seed_membership(
    session: AsyncSession,
    user_id: UserId,
    inviter_id: UserId,
    invitation_ttl_days: int,
    seed: SeedMembership,
) -> None:
    # At most one row per (organization, user) -- the unique constraint --
    # so that pair is what "already seeded" means.
    already_exists = (
        await session.execute(
            select(organization_memberships_table.c.id).where(
                organization_memberships_table.c.organization_id == seed.organization_id,
                organization_memberships_table.c.user_id == user_id,
            )
        )
    ).first()
    if already_exists is not None:
        logger.info("Seed membership %s in %s already exists, skipping.", seed.username, seed.organization_id)
        return

    now = datetime.now(UTC)
    created_at: datetime
    accepted_at: datetime | None
    expires_at: datetime | None
    if seed.state == "accepted":
        created_at, accepted_at, expires_at = now, now, None
    elif seed.state == "pending":
        # Exactly what InviteOrganizationMember writes: expires after the TTL.
        created_at, accepted_at, expires_at = now, None, now + timedelta(days=invitation_ttl_days)
    else:
        # Sent 10 days ago and lapsed 3 days ago -- clearly expired.
        created_at, accepted_at, expires_at = now - timedelta(days=10), None, now - timedelta(days=3)
    session.add(
        OrganizationMembership(
            id_=OrganizationMembershipId(seed.id) if seed.id is not None else create_organization_membership_id(),
            organization_id=OrganizationId(seed.organization_id),
            user_id=user_id,
            role=seed.role,
            invited_by_user_id=inviter_id,
            created_at=UtcDatetime(created_at),
            accepted_at=UtcDatetime(accepted_at) if accepted_at is not None else None,
            expires_at=UtcDatetime(expires_at) if expires_at is not None else None,
        )
    )
    logger.info("Seeded %s membership: %s in %s (%s)", seed.state, seed.username, seed.organization_id, seed.role)


async def seed_organizations(
    *,
    session: AsyncSession,
    user_ids_by_username: Mapping[str, UserId],
    container: AsyncContainer,
) -> None:
    # Organizations, then memberships, with a flush between: neither has a
    # relationship() the unit-of-work could order them by. seed_db.py commits
    # once, after every unit's seeds.
    organization_settings = await container.get(OrganizationSettings)
    owner_by_organization = {seed_org.id: seed_org.owner_username for seed_org in SEED_ORGANIZATIONS}
    for seed_org in SEED_ORGANIZATIONS:
        await _seed_organization(session, user_ids_by_username[seed_org.owner_username], seed_org)
    await session.flush()
    for seed_membership in SEED_MEMBERSHIPS:
        await _seed_membership(
            session,
            user_id=user_ids_by_username[seed_membership.username],
            # Every seeded invitation was "sent" by that organization's owner.
            inviter_id=user_ids_by_username[owner_by_organization[seed_membership.organization_id]],
            invitation_ttl_days=organization_settings.INVITATION_TTL_DAYS,
            seed=seed_membership,
        )
