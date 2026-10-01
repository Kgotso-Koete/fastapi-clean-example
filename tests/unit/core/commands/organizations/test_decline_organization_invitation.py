from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.commands.decline_organization_invitation import (
    DeclineOrganizationInvitation,
    DeclineOrganizationInvitationRequest,
)
from app.core.commands.organization_exceptions import MembershipNotFoundError
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.entities.user import User
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager
from tests.unit.core.common.authorization.factories import (
    FakeAccessRevoker,
    FakeAuthzUserFinder,
    FakeIdentityProvider,
    create_current_user_service,
)
from tests.unit.core.common.services.factories import create_user

# DeclineOrganizationInvitation (docs/plans/9-organizations.md, Step 6): the
# invitee turns down their own PENDING invitation, which deletes the row --
# expired or not. Same "is this invitation mine?" authorization and scoped
# lookup as AcceptOrganizationInvitation. An accepted membership is not an
# invitation: leaving goes through RemoveOrganizationMember (Step 7), which
# enforces the last-owner rule.

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class _FakeOrganizationRepository(OrganizationRepository):
    """Holds at most one membership, with the same scoped
    get_membership_by_id() as the real adapter (both ids must match).
    Records every delete_membership() call and every lookup."""

    def __init__(self, membership: OrganizationMembership | None = None) -> None:
        self._membership = membership
        self.deleted: list[OrganizationMembership] = []
        self.lookups: list[tuple[OrganizationId, OrganizationMembershipId]] = []

    def add(self, organization: Organization) -> None:
        raise NotImplementedError

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        raise NotImplementedError

    def add_membership(self, membership: OrganizationMembership) -> None:
        raise NotImplementedError

    async def get_membership_by_id(
        self,
        organization_id: OrganizationId,
        membership_id: OrganizationMembershipId,
    ) -> OrganizationMembership | None:
        self.lookups.append((organization_id, membership_id))
        m = self._membership
        if m is not None and m.organization_id == organization_id and m.id_ == membership_id:
            return m
        return None

    async def get_membership_for_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> OrganizationMembership | None:
        raise NotImplementedError

    async def delete_membership(self, membership: OrganizationMembership) -> None:
        self.deleted.append(membership)

    async def count_owners(self, organization_id: OrganizationId) -> int:
        raise NotImplementedError


def _membership(
    *,
    invitee: User,
    organization_id: OrganizationId,
    accepted: bool = False,
    expired: bool = False,
) -> OrganizationMembership:
    # A pending invitation by default (valid for another 6 days); `expired`
    # puts its expiry in the past; `accepted` makes it a real membership.
    expires_at = _NOW - timedelta(days=1) if expired else _NOW + timedelta(days=6)
    return OrganizationMembership(
        id_=OrganizationMembershipId(uuid4()),
        organization_id=organization_id,
        user_id=invitee.id_,
        role=OrganizationRole.MEMBER,
        invited_by_user_id=UserId(uuid4()),
        created_at=UtcDatetime(_NOW - timedelta(days=8)),
        accepted_at=UtcDatetime(_NOW - timedelta(days=7)) if accepted else None,
        expires_at=None if accepted else UtcDatetime(expires_at),
    )


def _make_sut(
    *,
    caller: User,
    repository: _FakeOrganizationRepository,
    transaction_manager: FakeTransactionManager,
    current_user_service: CurrentUserService | None = None,
) -> DeclineOrganizationInvitation:
    return DeclineOrganizationInvitation(
        current_user_service=current_user_service or create_current_user_service(caller),
        organization_repository=repository,
        transaction_manager=transaction_manager,
    )


def _request(
    organization_id: OrganizationId,
    membership_id: OrganizationMembershipId,
) -> DeclineOrganizationInvitationRequest:
    return DeclineOrganizationInvitationRequest(organization_id=organization_id, membership_id=membership_id)


# --- 1 & 2. Declining deletes the pending row, expired or not -----------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expired",
    [
        pytest.param(False, id="pending_invitation"),
        pytest.param(True, id="expired_invitation"),
    ],
)
async def test_the_invitee_declines_their_own_invitation_which_deletes_it(expired: bool) -> None:
    invitee = create_user()
    organization_id = create_organization_id()
    invitation = _membership(invitee=invitee, organization_id=organization_id, expired=expired)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=invitee, repository=repository, transaction_manager=transaction_manager)

    await sut.execute(_request(organization_id, invitation.id_))

    assert repository.deleted == [invitation]
    assert transaction_manager.commit_call_count == 1


# --- 3 & 4. Not yours, or not there -------------------------------------------


@pytest.mark.asyncio
async def test_someone_elses_invitation_is_reported_as_not_found() -> None:
    invitee = create_user()
    someone_else = create_user()
    organization_id = create_organization_id()
    invitation = _membership(invitee=invitee, organization_id=organization_id)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=someone_else, repository=repository, transaction_manager=transaction_manager)

    with pytest.raises(MembershipNotFoundError):
        await sut.execute(_request(organization_id, invitation.id_))

    assert repository.deleted == []
    assert transaction_manager.commit_call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "look_in_another_organization",
    [
        pytest.param(False, id="unknown_membership_id"),
        pytest.param(True, id="membership_of_another_organization"),
    ],
)
async def test_an_unknown_or_out_of_scope_membership_is_not_found(look_in_another_organization: bool) -> None:
    invitee = create_user()
    organization_id = create_organization_id()
    invitation = _membership(invitee=invitee, organization_id=organization_id)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=invitee, repository=repository, transaction_manager=transaction_manager)
    if look_in_another_organization:
        request = _request(create_organization_id(), invitation.id_)
    else:
        request = _request(organization_id, OrganizationMembershipId(uuid4()))

    with pytest.raises(MembershipNotFoundError):
        await sut.execute(request)

    assert repository.deleted == []
    assert transaction_manager.commit_call_count == 0


# --- 5. An accepted membership is not an invitation ---------------------------


@pytest.mark.asyncio
async def test_an_accepted_membership_cannot_be_declined() -> None:
    # "No pending invitation with that id." Leaving an organization goes
    # through RemoveOrganizationMember, which enforces that the last OWNER can
    # never leave -- decline must not become a back door around that rule.
    member = create_user()
    organization_id = create_organization_id()
    membership = _membership(invitee=member, organization_id=organization_id, accepted=True)
    repository = _FakeOrganizationRepository(membership)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=member, repository=repository, transaction_manager=transaction_manager)

    with pytest.raises(MembershipNotFoundError):
        await sut.execute(_request(organization_id, membership.id_))

    assert repository.deleted == []
    assert transaction_manager.commit_call_count == 0


# --- 6. Unresolvable caller ---------------------------------------------------


@pytest.mark.asyncio
async def test_an_unresolvable_caller_is_refused_before_any_lookup() -> None:
    invitee = create_user()
    organization_id = create_organization_id()
    invitation = _membership(invitee=invitee, organization_id=organization_id)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(
        caller=invitee,
        repository=repository,
        transaction_manager=transaction_manager,
        current_user_service=CurrentUserService(
            identity_provider=FakeIdentityProvider(invitee.id_),
            authz_user_finder=FakeAuthzUserFinder(None),
            access_revoker=FakeAccessRevoker(),
        ),
    )

    with pytest.raises(AuthorizationError):
        await sut.execute(_request(organization_id, invitation.id_))

    assert repository.lookups == []
    assert repository.deleted == []
    assert transaction_manager.commit_call_count == 0
