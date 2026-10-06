from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.entities.types_ import UserId
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.factories.organization_membership_id_factory import create_organization_membership_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.adapters.sqla_membership_checker import SqlaMembershipChecker
from tests.integration.with_infra.factories import create_user

# SqlaMembershipChecker answers exactly one question for CanAccessOrganization:
# "what ACCEPTED role, if any, does this user hold in THIS organization?"
# None is the only safe answer for anything short of an accepted membership
# in that exact organization -- CanAccessOrganization denies on None.


async def _persist_user(it_session: AsyncSession, it_user_service: UserService) -> UserId:
    user = create_user(it_user_service)
    it_session.add(user)
    await it_session.commit()
    return user.id_


async def _persist_organization(
    it_session: AsyncSession,
    *,
    created_by_user_id: UserId,
    name: str = "Avengers",
) -> Organization:
    organization = Organization(
        id_=create_organization_id(),
        name=OrganizationName(name),
        description=Description(f"The {name}."),
        created_by_user_id=created_by_user_id,
        created_at=UtcDatetime(datetime.now(UTC)),
    )
    it_session.add(organization)
    await it_session.commit()
    return organization


async def _persist_membership(
    it_session: AsyncSession,
    *,
    organization_id: OrganizationId,
    user_id: UserId,
    invited_by_user_id: UserId,
    role: OrganizationRole = OrganizationRole.MEMBER,
    accepted: bool = True,
) -> None:
    now = UtcDatetime(datetime.now(UTC))
    it_session.add(
        OrganizationMembership(
            id_=create_organization_membership_id(),
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            invited_by_user_id=invited_by_user_id,
            created_at=now,
            # accepted=False leaves accepted_at as None -- a still-pending invite.
            accepted_at=now if accepted else None,
            # The entity requires a pending invite to expire and an accepted
            # membership not to; 7 days mirrors ORGANIZATION_INVITATION_TTL_DAYS.
            expires_at=None if accepted else UtcDatetime(now.value + timedelta(days=7)),
        )
    )
    await it_session.commit()


@pytest.mark.asyncio
async def test_an_accepted_membership_resolves_to_its_role(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await _persist_user(it_session, it_user_service)
    admin = await _persist_user(it_session, it_user_service)
    organization = await _persist_organization(it_session, created_by_user_id=owner)
    await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=admin,
        invited_by_user_id=owner,
        role=OrganizationRole.ADMIN,
    )
    sut = SqlaMembershipChecker(it_session)

    role = await sut.get_role(admin, organization.id_)

    assert role == OrganizationRole.ADMIN


@pytest.mark.asyncio
async def test_a_pending_invitation_resolves_to_none(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Invited, even as OWNER, but not yet accepted -- not a member, so no
    # role at all. Otherwise an unaccepted invite would already grant access.
    owner = await _persist_user(it_session, it_user_service)
    invitee = await _persist_user(it_session, it_user_service)
    organization = await _persist_organization(it_session, created_by_user_id=owner)
    await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=invitee,
        invited_by_user_id=owner,
        role=OrganizationRole.OWNER,
        accepted=False,
    )
    sut = SqlaMembershipChecker(it_session)

    role = await sut.get_role(invitee, organization.id_)

    assert role is None


@pytest.mark.asyncio
async def test_a_non_member_resolves_to_none(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await _persist_user(it_session, it_user_service)
    stranger = await _persist_user(it_session, it_user_service)
    organization = await _persist_organization(it_session, created_by_user_id=owner)
    await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=owner,
        invited_by_user_id=owner,
        role=OrganizationRole.OWNER,
    )
    sut = SqlaMembershipChecker(it_session)

    role = await sut.get_role(stranger, organization.id_)

    assert role is None


@pytest.mark.asyncio
async def test_a_membership_in_another_organization_resolves_to_none(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The cross-tenant case: being OWNER of organization B must grant
    # nothing at all in organization A.
    owner_a = await _persist_user(it_session, it_user_service)
    owner_b = await _persist_user(it_session, it_user_service)
    organization_a = await _persist_organization(it_session, created_by_user_id=owner_a, name="Avengers")
    organization_b = await _persist_organization(it_session, created_by_user_id=owner_b, name="X-Men")
    await _persist_membership(
        it_session,
        organization_id=organization_b.id_,
        user_id=owner_b,
        invited_by_user_id=owner_b,
        role=OrganizationRole.OWNER,
    )
    sut = SqlaMembershipChecker(it_session)

    role = await sut.get_role(owner_b, organization_a.id_)

    assert role is None
