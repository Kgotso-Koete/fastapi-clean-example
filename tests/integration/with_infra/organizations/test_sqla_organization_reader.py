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
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams
from app.outbound.adapters.sqla_organization_reader import SqlaOrganizationReader
from tests.integration.with_infra.factories import create_user

# Mirrors test_sqla_api_key_reader.py: paginated lists with a total, sorting,
# and an empty case. The reader performs NO authorization of its own -- who
# may call each query (e.g. "only a member may list members") is enforced
# one layer up, by the query use cases via CurrentOrganizationService, exactly
# like SqlaApiKeyReader leaves ownership checks to GetApiKeyUsageStats.

_DEFAULT_PAGINATION = OffsetPaginationParams(limit=50, offset=0)
_SORT_BY_CREATED_AT_ASC = SortingParams(field="created_at", order=SortingOrder.ASC)


async def _persist_user(
    it_session: AsyncSession,
    it_user_service: UserService,
    *,
    username: str | None = None,
) -> UserId:
    # An explicit username lets a test assert on it by value; otherwise a
    # random one is generated.
    user = create_user(it_user_service, raw_username=username)
    it_session.add(user)
    await it_session.commit()
    return user.id_


async def _persist_organization(
    it_session: AsyncSession,
    *,
    created_by_user_id: UserId,
    name: str = "Avengers",
    created_at: datetime | None = None,
) -> Organization:
    organization = Organization(
        id_=create_organization_id(),
        name=OrganizationName(name),
        description=Description(f"The {name}."),
        created_by_user_id=created_by_user_id,
        created_at=UtcDatetime(created_at or datetime.now(UTC)),
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
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> OrganizationMembership:
    now = UtcDatetime(created_at or datetime.now(UTC))
    # A pending invite expires 7 days after it was created unless a test says
    # otherwise (e.g. an expiry already in the past).
    pending_expiry = UtcDatetime(expires_at or now.value + timedelta(days=7))
    membership = OrganizationMembership(
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
        expires_at=None if accepted else pending_expiry,
    )
    it_session.add(membership)
    await it_session.commit()
    return membership


# ---------------------------------------------------------------------------
# list_for_user -- backs ListMyOrganizations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_user_returns_only_organizations_with_an_accepted_membership(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    caller = await _persist_user(it_session, it_user_service)
    owner = await _persist_user(it_session, it_user_service)
    org_a = await _persist_organization(it_session, created_by_user_id=owner, name="Avengers")
    org_b = await _persist_organization(it_session, created_by_user_id=owner, name="X-Men")
    await _persist_organization(it_session, created_by_user_id=owner, name="Midnight Suns")
    await _persist_membership(it_session, organization_id=org_a.id_, user_id=caller, invited_by_user_id=owner)
    # A pending invite is NOT membership -- it belongs to ListMyInvitations.
    await _persist_membership(
        it_session, organization_id=org_b.id_, user_id=caller, invited_by_user_id=owner, accepted=False
    )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_for_user(caller, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    assert result["total"] == 1
    assert [o["name"] for o in result["organizations"]] == ["Avengers"]


@pytest.mark.asyncio
async def test_list_for_user_includes_the_description_the_callers_role_and_member_count(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    caller = await _persist_user(it_session, it_user_service)
    member_2 = await _persist_user(it_session, it_user_service)
    member_3 = await _persist_user(it_session, it_user_service)
    pending_invitee = await _persist_user(it_session, it_user_service)
    other_org_owner = await _persist_user(it_session, it_user_service)
    org_a = await _persist_organization(it_session, created_by_user_id=caller, name="Avengers")
    org_b = await _persist_organization(it_session, created_by_user_id=other_org_owner, name="X-Men")
    await _persist_membership(
        it_session,
        organization_id=org_a.id_,
        user_id=caller,
        invited_by_user_id=caller,
        role=OrganizationRole.ADMIN,
    )
    await _persist_membership(it_session, organization_id=org_a.id_, user_id=member_2, invited_by_user_id=caller)
    await _persist_membership(it_session, organization_id=org_a.id_, user_id=member_3, invited_by_user_id=caller)
    await _persist_membership(
        it_session, organization_id=org_a.id_, user_id=pending_invitee, invited_by_user_id=caller, accepted=False
    )
    # Another organization's member -- must never leak into org A's count.
    await _persist_membership(
        it_session,
        organization_id=org_b.id_,
        user_id=other_org_owner,
        invited_by_user_id=other_org_owner,
        role=OrganizationRole.OWNER,
    )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_for_user(caller, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    assert len(result["organizations"]) == 1
    organization = result["organizations"][0]
    assert organization["id"] == org_a.id_
    # Every organization explains itself, so the list carries it --
    # _persist_organization describes org A as "The Avengers.".
    assert organization["description"] == "The Avengers."
    assert organization["role"] == OrganizationRole.ADMIN
    # 3 accepted members (caller, member_2, member_3) -- the pending invite
    # and org B's owner don't count.
    assert organization["member_count"] == 3


@pytest.mark.asyncio
async def test_list_for_user_paginates_and_reports_total(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    caller = await _persist_user(it_session, it_user_service)
    base = datetime.now(UTC)
    for i, name in enumerate(["Avengers", "X-Men", "Midnight Suns"]):
        organization = await _persist_organization(
            it_session, created_by_user_id=caller, name=name, created_at=base + timedelta(seconds=i)
        )
        await _persist_membership(
            it_session,
            organization_id=organization.id_,
            user_id=caller,
            invited_by_user_id=caller,
            role=OrganizationRole.OWNER,
        )
    sut = SqlaOrganizationReader(it_session)

    page_1 = await sut.list_for_user(
        caller, pagination=OffsetPaginationParams(limit=2, offset=0), sorting=_SORT_BY_CREATED_AT_ASC
    )
    page_2 = await sut.list_for_user(
        caller, pagination=OffsetPaginationParams(limit=2, offset=2), sorting=_SORT_BY_CREATED_AT_ASC
    )

    # total reflects the full matching set, not just the page size -- both
    # pages must agree on it.
    assert page_1["total"] == 3
    assert page_2["total"] == 3
    assert [o["name"] for o in page_1["organizations"]] == ["Avengers", "X-Men"]
    assert [o["name"] for o in page_2["organizations"]] == ["Midnight Suns"]


@pytest.mark.asyncio
async def test_list_for_user_sorts_descending_when_requested(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    caller = await _persist_user(it_session, it_user_service)
    base = datetime.now(UTC)
    for i, name in enumerate(["Oldest", "Newest"]):
        organization = await _persist_organization(
            it_session, created_by_user_id=caller, name=name, created_at=base + timedelta(seconds=i)
        )
        await _persist_membership(
            it_session, organization_id=organization.id_, user_id=caller, invited_by_user_id=caller
        )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_for_user(
        caller,
        pagination=_DEFAULT_PAGINATION,
        sorting=SortingParams(field="created_at", order=SortingOrder.DESC),
    )

    assert [o["name"] for o in result["organizations"]] == ["Newest", "Oldest"]


@pytest.mark.asyncio
async def test_list_for_user_returns_empty_with_correct_total_for_a_user_with_no_organizations(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    caller = await _persist_user(it_session, it_user_service)
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_for_user(caller, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    assert result == {"organizations": [], "total": 0, "limit": 50, "offset": 0}


# ---------------------------------------------------------------------------
# list_members -- backs ListOrganizationMembers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_members_returns_accepted_and_pending_members_of_that_organization_only(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await _persist_user(it_session, it_user_service, username="tony_stark")
    invitee = await _persist_user(it_session, it_user_service, username="peter_parker")
    outsider = await _persist_user(it_session, it_user_service, username="charles_xavier")
    base = datetime.now(UTC)
    organization = await _persist_organization(it_session, created_by_user_id=owner, name="Avengers")
    other_organization = await _persist_organization(it_session, created_by_user_id=outsider, name="X-Men")
    await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=owner,
        invited_by_user_id=owner,
        role=OrganizationRole.OWNER,
        created_at=base,
    )
    pending = await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=invitee,
        invited_by_user_id=owner,
        accepted=False,
        created_at=base + timedelta(seconds=1),
    )
    # Another organization's member -- must never appear in this list.
    await _persist_membership(
        it_session,
        organization_id=other_organization.id_,
        user_id=outsider,
        invited_by_user_id=outsider,
        role=OrganizationRole.OWNER,
    )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_members(organization.id_, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    members = result["members"]
    assert [m["username"] for m in members] == ["tony_stark", "peter_parker"]
    assert members[0]["role"] == OrganizationRole.OWNER
    assert members[0]["accepted_at"] is not None
    assert members[1]["membership_id"] == pending.id_
    assert members[1]["role"] == OrganizationRole.MEMBER
    # accepted_at None = a still-pending invitation, shown as such.
    assert members[1]["accepted_at"] is None
    # expires_at lets admins see which invitations have lapsed; a real
    # member's row never expires.
    assert members[0]["expires_at"] is None
    assert pending.expires_at is not None
    assert members[1]["expires_at"] == pending.expires_at.value
    # username is the ONLY personal detail exposed -- every member can call
    # this query, so email/phone must never be part of a row. Pinning the
    # exact key set means a future column added here has to be a deliberate,
    # test-visible decision.
    assert set(members[0].keys()) == {"membership_id", "username", "role", "accepted_at", "expires_at", "created_at"}


@pytest.mark.asyncio
async def test_list_members_member_count_counts_only_accepted_members(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await _persist_user(it_session, it_user_service)
    member = await _persist_user(it_session, it_user_service)
    invitee = await _persist_user(it_session, it_user_service)
    organization = await _persist_organization(it_session, created_by_user_id=owner)
    await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=owner,
        invited_by_user_id=owner,
        role=OrganizationRole.OWNER,
    )
    await _persist_membership(it_session, organization_id=organization.id_, user_id=member, invited_by_user_id=owner)
    await _persist_membership(
        it_session, organization_id=organization.id_, user_id=invitee, invited_by_user_id=owner, accepted=False
    )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_members(organization.id_, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    # total counts the ROWS being listed (pending invites included);
    # member_count counts actual MEMBERS (accepted only). They differ
    # exactly by the number of pending invitations.
    assert result["total"] == 3
    assert result["member_count"] == 2


@pytest.mark.asyncio
async def test_list_members_paginates_and_reports_total(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await _persist_user(it_session, it_user_service, username="steve_rogers")
    base = datetime.now(UTC)
    organization = await _persist_organization(it_session, created_by_user_id=owner)
    await _persist_membership(
        it_session,
        organization_id=organization.id_,
        user_id=owner,
        invited_by_user_id=owner,
        role=OrganizationRole.OWNER,
        created_at=base,
    )
    for i, username in enumerate(["natasha_romanoff", "bruce_banner"], start=1):
        user_id = await _persist_user(it_session, it_user_service, username=username)
        await _persist_membership(
            it_session,
            organization_id=organization.id_,
            user_id=user_id,
            invited_by_user_id=owner,
            created_at=base + timedelta(seconds=i),
        )
    sut = SqlaOrganizationReader(it_session)

    page_1 = await sut.list_members(
        organization.id_, pagination=OffsetPaginationParams(limit=2, offset=0), sorting=_SORT_BY_CREATED_AT_ASC
    )
    page_2 = await sut.list_members(
        organization.id_, pagination=OffsetPaginationParams(limit=2, offset=2), sorting=_SORT_BY_CREATED_AT_ASC
    )

    assert page_1["total"] == 3
    assert page_2["total"] == 3
    # member_count is the organization's, not the page's -- same on both.
    assert page_1["member_count"] == 3
    assert page_2["member_count"] == 3
    assert [m["username"] for m in page_1["members"]] == ["steve_rogers", "natasha_romanoff"]
    assert [m["username"] for m in page_2["members"]] == ["bruce_banner"]


# ---------------------------------------------------------------------------
# list_invitations_for_user -- backs ListMyInvitations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_invitations_for_user_returns_only_the_callers_pending_invitations(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    caller = await _persist_user(it_session, it_user_service)
    inviter = await _persist_user(it_session, it_user_service, username="nick_fury")
    someone_else = await _persist_user(it_session, it_user_service)
    org_a = await _persist_organization(it_session, created_by_user_id=inviter, name="Avengers")
    org_b = await _persist_organization(it_session, created_by_user_id=inviter, name="X-Men")
    org_c = await _persist_organization(it_session, created_by_user_id=inviter, name="Midnight Suns")
    invitation = await _persist_membership(
        it_session,
        organization_id=org_a.id_,
        user_id=caller,
        invited_by_user_id=inviter,
        role=OrganizationRole.ADMIN,
        accepted=False,
    )
    # Already accepted -- that's membership (ListMyOrganizations), not an invite.
    await _persist_membership(it_session, organization_id=org_b.id_, user_id=caller, invited_by_user_id=inviter)
    # Someone else's pending invite -- must never be visible to the caller.
    await _persist_membership(
        it_session, organization_id=org_c.id_, user_id=someone_else, invited_by_user_id=inviter, accepted=False
    )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_invitations_for_user(
        caller, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC
    )

    assert result["total"] == 1
    assert len(result["invitations"]) == 1
    row = result["invitations"][0]
    # membership_id + organization_id are exactly what the accept route
    # (/organizations/{organization_id}/members/{membership_id}/accept/)
    # needs -- the whole point of this query.
    assert row["membership_id"] == invitation.id_
    assert row["organization_id"] == org_a.id_
    assert row["organization_name"] == "Avengers"
    # The invitee isn't a member yet, so this is where they learn what the
    # organization is before deciding to accept.
    assert row["organization_description"] == "The Avengers."
    assert row["role"] == OrganizationRole.ADMIN
    assert row["invited_by_username"] == "nick_fury"


@pytest.mark.asyncio
async def test_list_invitations_for_user_leaves_out_expired_invitations_and_shows_the_expiry(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # An expired invitation can no longer be accepted (410), so listing it as
    # "waiting for you" would be misleading. The live one carries its expiry,
    # so the invitee knows the deadline.
    caller = await _persist_user(it_session, it_user_service)
    inviter = await _persist_user(it_session, it_user_service)
    live_org = await _persist_organization(it_session, created_by_user_id=inviter, name="Avengers")
    lapsed_org = await _persist_organization(it_session, created_by_user_id=inviter, name="X-Men")
    live = await _persist_membership(
        it_session, organization_id=live_org.id_, user_id=caller, invited_by_user_id=inviter, accepted=False
    )
    await _persist_membership(
        it_session,
        organization_id=lapsed_org.id_,
        user_id=caller,
        invited_by_user_id=inviter,
        accepted=False,
        created_at=datetime.now(UTC) - timedelta(days=10),
        expires_at=datetime.now(UTC) - timedelta(days=3),
    )
    sut = SqlaOrganizationReader(it_session)

    result = await sut.list_invitations_for_user(
        caller, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC
    )

    assert result["total"] == 1
    assert [row["membership_id"] for row in result["invitations"]] == [live.id_]
    assert live.expires_at is not None
    assert result["invitations"][0]["expires_at"] == live.expires_at.value
