from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.entities.types_ import UserId
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.factories.organization_membership_id_factory import create_organization_membership_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.adapters.sqla_organization_repository import SqlaOrganizationRepository
from tests.integration.with_infra.factories import create_user

# Mirrors test_sqla_api_key_repository.py: no DI container involved at this
# step -- the repository is constructed directly against it_session, just
# with a real Postgres session underneath.


async def _persist_user(it_session: AsyncSession, it_user_service: UserService) -> UserId:
    # Only a real users.id row is needed, to satisfy the foreign keys on
    # organizations.created_by_user_id and organization_memberships.user_id /
    # invited_by_user_id.
    user = create_user(it_user_service)
    it_session.add(user)
    await it_session.commit()
    return user.id_


def _build_organization(*, created_by_user_id: UserId, name: str = "Avengers") -> Organization:
    return Organization(
        id_=create_organization_id(),
        name=OrganizationName(name),
        created_by_user_id=created_by_user_id,
        created_at=UtcDatetime(datetime.now(UTC)),
    )


def _build_membership(
    *,
    organization_id: OrganizationId,
    user_id: UserId,
    invited_by_user_id: UserId,
    role: OrganizationRole = OrganizationRole.MEMBER,
    accepted: bool = True,
) -> OrganizationMembership:
    now = UtcDatetime(datetime.now(UTC))
    return OrganizationMembership(
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


async def _persist_organization(
    it_session: AsyncSession,
    sut: SqlaOrganizationRepository,
    *,
    created_by_user_id: UserId,
    name: str = "Avengers",
) -> Organization:
    organization = _build_organization(created_by_user_id=created_by_user_id, name=name)
    sut.add(organization)
    await it_session.commit()
    return organization


@pytest.mark.asyncio
async def test_add_then_get_by_id_round_trips(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=user_id)
    # Drop every object from the session's identity map, so get_by_id()
    # below has to actually SELECT the row back from Postgres rather than
    # hand back the same in-memory object that was just added.
    it_session.expunge_all()

    found = await sut.get_by_id(organization.id_)

    assert found is not None
    assert found.id_ == organization.id_
    # Read back from Postgres (expunge_all above) as the value object, not a
    # raw str -- proves the mapping wraps the column in OrganizationName.
    assert found.name == OrganizationName("Avengers")
    assert found.created_by_user_id == user_id
    assert found.created_at == organization.created_at


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_an_unknown_id(it_session: AsyncSession) -> None:
    sut = SqlaOrganizationRepository(it_session)

    found = await sut.get_by_id(create_organization_id())

    assert found is None


@pytest.mark.asyncio
async def test_a_pending_membership_round_trips_with_accepted_at_none(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The LOAD half of the nullable-UtcDatetime composite() bug from
    # docs/plans/8-public-api-key-auth.md's Step 3: reading a NULL
    # accepted_at back from Postgres must not crash.
    owner_id = await _persist_user(it_session, it_user_service)
    invitee_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    membership = _build_membership(
        organization_id=organization.id_,
        user_id=invitee_id,
        invited_by_user_id=owner_id,
        accepted=False,
    )
    sut.add_membership(membership)
    await it_session.commit()
    it_session.expunge_all()

    found = await sut.get_membership_by_id(organization.id_, membership.id_)

    assert found is not None
    assert found.organization_id == organization.id_
    assert found.user_id == invitee_id
    assert found.role == OrganizationRole.MEMBER
    assert found.invited_by_user_id == owner_id
    assert found.accepted_at is None
    assert not found.is_accepted


@pytest.mark.asyncio
async def test_an_accepted_membership_round_trips_its_accepted_at(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The WRITE half of the same bug: a set accepted_at must actually be
    # written to the nullable column, and read back as the same UtcDatetime.
    owner_id = await _persist_user(it_session, it_user_service)
    invitee_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    membership = _build_membership(
        organization_id=organization.id_,
        user_id=invitee_id,
        invited_by_user_id=owner_id,
        role=OrganizationRole.ADMIN,
        accepted=True,
    )
    sut.add_membership(membership)
    await it_session.commit()
    it_session.expunge_all()

    found = await sut.get_membership_by_id(organization.id_, membership.id_)

    assert found is not None
    assert found.role == OrganizationRole.ADMIN
    assert found.is_accepted
    assert found.accepted_at == membership.accepted_at


@pytest.mark.asyncio
async def test_get_membership_by_id_returns_none_for_a_membership_in_another_organization(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Scoped lookup, approved change (a): a membership id is only ever
    # resolved WITHIN the organization named in the URL. Without this, an
    # ADMIN of organization A could act on (e.g. remove) a member of
    # organization B just by knowing that membership's id. Mirrors
    # apptension/saas-boilerplate's
    # test_delete_tenant_membership_with_different_tenant_id.
    owner_id = await _persist_user(it_session, it_user_service)
    member_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization_a = await _persist_organization(it_session, sut, created_by_user_id=owner_id, name="Avengers")
    organization_b = await _persist_organization(it_session, sut, created_by_user_id=owner_id, name="X-Men")
    membership_in_b = _build_membership(
        organization_id=organization_b.id_,
        user_id=member_id,
        invited_by_user_id=owner_id,
    )
    sut.add_membership(membership_in_b)
    await it_session.commit()

    found_via_a = await sut.get_membership_by_id(organization_a.id_, membership_in_b.id_)
    found_via_b = await sut.get_membership_by_id(organization_b.id_, membership_in_b.id_)

    assert found_via_a is None
    # Sanity check that the None above is really the scoping at work, not
    # the row simply being missing.
    assert found_via_b is not None


@pytest.mark.asyncio
async def test_count_owners_counts_only_accepted_owners_of_that_organization(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # What Step 7's LastOwnerError will depend on. Only an ACCEPTED OWNER
    # counts -- a pending OWNER invite can't run the organization yet, so
    # it must never be what lets the last real owner be removed. Matches
    # apptension/saas-boilerplate, whose default membership manager only
    # ever sees accepted rows.
    owner_1 = await _persist_user(it_session, it_user_service)
    owner_2 = await _persist_user(it_session, it_user_service)
    pending_owner = await _persist_user(it_session, it_user_service)
    admin = await _persist_user(it_session, it_user_service)
    member = await _persist_user(it_session, it_user_service)
    other_org_owner = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_1, name="Avengers")
    other_organization = await _persist_organization(it_session, sut, created_by_user_id=other_org_owner, name="X-Men")
    org_id = organization.id_
    for user_id, role, accepted in [
        (owner_1, OrganizationRole.OWNER, True),
        (owner_2, OrganizationRole.OWNER, True),
        (pending_owner, OrganizationRole.OWNER, False),
        (admin, OrganizationRole.ADMIN, True),
        (member, OrganizationRole.MEMBER, True),
    ]:
        sut.add_membership(
            _build_membership(
                organization_id=org_id,
                user_id=user_id,
                invited_by_user_id=owner_1,
                role=role,
                accepted=accepted,
            )
        )
    # An owner of a DIFFERENT organization -- must not leak into the count.
    sut.add_membership(
        _build_membership(
            organization_id=other_organization.id_,
            user_id=other_org_owner,
            invited_by_user_id=other_org_owner,
            role=OrganizationRole.OWNER,
        )
    )
    await it_session.commit()

    count = await sut.count_owners(org_id)
    other_count = await sut.count_owners(other_organization.id_)

    assert count == 2
    assert other_count == 1


@pytest.mark.asyncio
async def test_a_second_membership_for_the_same_user_and_organization_is_rejected(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Approved change (b): a unique (organization_id, user_id) constraint.
    # Without it, inviting the same user twice creates two rows, and
    # MembershipChecker.get_role() would have two candidate roles to pick
    # from. Mirrors apptension/saas-boilerplate's
    # unique_non_null_user_and_tenant constraint. Enforced by the database
    # itself, so it surfaces on commit, not on add_membership().
    owner_id = await _persist_user(it_session, it_user_service)
    invitee_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    sut.add_membership(
        _build_membership(organization_id=organization.id_, user_id=invitee_id, invited_by_user_id=owner_id)
    )
    await it_session.commit()

    sut.add_membership(
        _build_membership(
            organization_id=organization.id_,
            user_id=invitee_id,
            invited_by_user_id=owner_id,
            accepted=False,
        )
    )

    with pytest.raises(IntegrityError):
        await it_session.commit()


# ---------------------------------------------------------------------------
# Invitation expiry (Step 6) -- expires_at must survive a real round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_pending_membership_round_trips_its_expires_at(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Both halves of the nullable-UtcDatetime story again, now for
    # expires_at: the value must really be WRITTEN to its column, and read
    # back as the same UtcDatetime -- otherwise every reloaded invitation
    # would silently lose its expiry, and is_expired() couldn't work.
    owner_id = await _persist_user(it_session, it_user_service)
    invitee_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    membership = _build_membership(
        organization_id=organization.id_,
        user_id=invitee_id,
        invited_by_user_id=owner_id,
        accepted=False,
    )
    sut.add_membership(membership)
    await it_session.commit()
    # Forces get_membership_by_id() to SELECT the row back from Postgres.
    it_session.expunge_all()

    found = await sut.get_membership_by_id(organization.id_, membership.id_)

    assert found is not None
    assert found.expires_at is not None
    assert found.expires_at == membership.expires_at
    # The reloaded row must behave, not just carry the value.
    assert found.is_expired(found.expires_at) is True


@pytest.mark.asyncio
async def test_an_accepted_membership_round_trips_with_expires_at_none(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The LOAD half for NULL: reading a NULL expires_at back must give None
    # (never crash), and a reloaded accepted membership never expires.
    owner_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    membership = _build_membership(
        organization_id=organization.id_,
        user_id=owner_id,
        invited_by_user_id=owner_id,
        role=OrganizationRole.OWNER,
        accepted=True,
    )
    sut.add_membership(membership)
    await it_session.commit()
    it_session.expunge_all()

    found = await sut.get_membership_by_id(organization.id_, membership.id_)

    assert found is not None
    assert found.expires_at is None
    assert found.is_expired(UtcDatetime(datetime(2099, 1, 1, tzinfo=UTC))) is False


# ---------------------------------------------------------------------------
# get_membership_for_user -- backs InviteOrganizationMember's duplicate check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_membership_for_user_finds_that_users_row_in_that_organization(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # InviteOrganizationMember needs "does this user already have a row
    # HERE?" before inserting -- to raise MembershipAlreadyExistsError (409),
    # or refresh an expired pending row, instead of hitting the unique
    # (organization_id, user_id) constraint as a raw IntegrityError.
    owner_id = await _persist_user(it_session, it_user_service)
    invitee_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    membership = _build_membership(
        organization_id=organization.id_,
        user_id=invitee_id,
        invited_by_user_id=owner_id,
        accepted=False,
    )
    sut.add_membership(membership)
    await it_session.commit()
    it_session.expunge_all()

    found = await sut.get_membership_for_user(organization.id_, invitee_id)

    assert found is not None
    assert found.id_ == membership.id_


@pytest.mark.asyncio
async def test_get_membership_for_user_is_scoped_to_one_organization(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A row in organization B must never count as "already a member" of A --
    # being in the X-Men mustn't block an invitation to the Avengers.
    owner_id = await _persist_user(it_session, it_user_service)
    member_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization_a = await _persist_organization(it_session, sut, created_by_user_id=owner_id, name="Avengers")
    organization_b = await _persist_organization(it_session, sut, created_by_user_id=owner_id, name="X-Men")
    sut.add_membership(
        _build_membership(organization_id=organization_b.id_, user_id=member_id, invited_by_user_id=owner_id)
    )
    await it_session.commit()

    found_in_a = await sut.get_membership_for_user(organization_a.id_, member_id)
    found_in_b = await sut.get_membership_for_user(organization_b.id_, member_id)

    assert found_in_a is None
    # Sanity check: the None above is the scoping, not a missing row.
    assert found_in_b is not None


@pytest.mark.asyncio
async def test_get_membership_for_user_returns_none_for_a_user_with_no_row(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner_id = await _persist_user(it_session, it_user_service)
    stranger_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)

    found = await sut.get_membership_for_user(organization.id_, stranger_id)

    assert found is None


# ---------------------------------------------------------------------------
# delete_membership -- backs Decline (Step 6) and Remove/Leave (Step 7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_membership_removes_only_that_row_once_committed(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Transactional like add_membership(): the delete is staged, and only
    # takes effect on commit. Other rows in the organization are untouched.
    owner_id = await _persist_user(it_session, it_user_service)
    invitee_id = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationRepository(it_session)
    organization = await _persist_organization(it_session, sut, created_by_user_id=owner_id)
    owner_membership = _build_membership(
        organization_id=organization.id_,
        user_id=owner_id,
        invited_by_user_id=owner_id,
        role=OrganizationRole.OWNER,
    )
    invitation = _build_membership(
        organization_id=organization.id_,
        user_id=invitee_id,
        invited_by_user_id=owner_id,
        accepted=False,
    )
    sut.add_membership(owner_membership)
    sut.add_membership(invitation)
    await it_session.commit()

    await sut.delete_membership(invitation)
    await it_session.commit()
    it_session.expunge_all()

    assert await sut.get_membership_by_id(organization.id_, invitation.id_) is None
    assert await sut.get_membership_by_id(organization.id_, owner_membership.id_) is not None
