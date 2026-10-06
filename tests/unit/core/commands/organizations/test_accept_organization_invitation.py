from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.commands.accept_organization_invitation import (
    AcceptOrganizationInvitation,
    AcceptOrganizationInvitationRequest,
)
from app.core.commands.organization_exceptions import InvitationExpiredError, MembershipNotFoundError
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
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager, FakeUtcTimer
from tests.unit.core.common.authorization.factories import (
    FakeAccessRevoker,
    FakeAuthzUserFinder,
    FakeIdentityProvider,
    create_current_user_service,
)
from tests.unit.core.common.services.factories import create_user

# AcceptOrganizationInvitation (docs/plans/9-organizations.md, Step 6): the
# invitee turns their own pending invitation into a membership. The invitee
# isn't a member yet, so this is NOT authorized via CurrentOrganizationService;
# the rule is simply "is this invitation mine?" (the same shape as
# CanManageSelf). Idempotent, like RevokeApiKey.

_NOW = UtcDatetime(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))


class _FakeOrganizationRepository(OrganizationRepository):
    """Holds at most one membership. get_membership_by_id() mirrors the real
    adapter's SCOPED lookup: it returns the membership only when BOTH the
    organization id and the membership id match, otherwise None. Records
    every lookup, so a test can prove none happened."""

    def __init__(self, membership: OrganizationMembership | None = None) -> None:
        self._membership = membership
        self.lookups: list[tuple[OrganizationId, OrganizationMembershipId]] = []

    def add(self, organization: Organization) -> None:
        raise NotImplementedError

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        raise NotImplementedError

    async def delete(self, organization: Organization) -> None:
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
        raise NotImplementedError

    async def count_owners(self, organization_id: OrganizationId) -> int:
        raise NotImplementedError


def _invitation(
    *,
    invitee: User,
    organization_id: OrganizationId,
    expires_at: UtcDatetime | None = None,
    accepted_at: UtcDatetime | None = None,
) -> OrganizationMembership:
    # A pending invitation by default, valid for another 6 days.
    if accepted_at is None and expires_at is None:
        expires_at = UtcDatetime(_NOW.value + timedelta(days=6))
    return OrganizationMembership(
        id_=OrganizationMembershipId(uuid4()),
        organization_id=organization_id,
        user_id=invitee.id_,
        role=OrganizationRole.MEMBER,
        invited_by_user_id=UserId(uuid4()),
        created_at=UtcDatetime(_NOW.value - timedelta(days=1)),
        accepted_at=accepted_at,
        expires_at=expires_at,
    )


def _make_sut(
    *,
    caller: User,
    repository: _FakeOrganizationRepository,
    transaction_manager: FakeTransactionManager,
    current_user_service: CurrentUserService | None = None,
) -> AcceptOrganizationInvitation:
    return AcceptOrganizationInvitation(
        current_user_service=current_user_service or create_current_user_service(caller),
        organization_repository=repository,
        utc_timer=FakeUtcTimer(_NOW),
        transaction_manager=transaction_manager,
    )


def _request(
    organization_id: OrganizationId,
    membership_id: OrganizationMembershipId,
) -> AcceptOrganizationInvitationRequest:
    return AcceptOrganizationInvitationRequest(organization_id=organization_id, membership_id=membership_id)


# --- 1. The happy path ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_invitee_accepts_their_own_pending_invitation() -> None:
    invitee = create_user()
    organization_id = create_organization_id()
    invitation = _invitation(invitee=invitee, organization_id=organization_id)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=invitee, repository=repository, transaction_manager=transaction_manager)

    await sut.execute(_request(organization_id, invitation.id_))

    # Now a real membership: accepted at "now", and it no longer expires.
    assert invitation.is_accepted is True
    assert invitation.accepted_at == _NOW
    assert invitation.expires_at is None
    assert transaction_manager.commit_call_count == 1


# --- 2. Idempotent ----------------------------------------------------------


@pytest.mark.asyncio
async def test_accepting_an_already_accepted_invitation_is_a_no_op() -> None:
    # A retried or replayed accept is safe: no error, nothing changes, and
    # no second commit -- the same pattern as RevokeApiKey.
    invitee = create_user()
    organization_id = create_organization_id()
    originally_accepted_at = UtcDatetime(_NOW.value - timedelta(hours=2))
    membership = _invitation(invitee=invitee, organization_id=organization_id, accepted_at=originally_accepted_at)
    repository = _FakeOrganizationRepository(membership)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=invitee, repository=repository, transaction_manager=transaction_manager)

    await sut.execute(_request(organization_id, membership.id_))

    assert membership.accepted_at == originally_accepted_at
    assert transaction_manager.commit_call_count == 0


# --- 3 & 4. Not yours, or not there -------------------------------------------


@pytest.mark.asyncio
async def test_someone_elses_invitation_is_reported_as_not_found() -> None:
    # 404, not 403: a user must not be able to confirm that another user's
    # invitation exists by probing membership ids.
    invitee = create_user()
    someone_else = create_user()
    organization_id = create_organization_id()
    invitation = _invitation(invitee=invitee, organization_id=organization_id)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=someone_else, repository=repository, transaction_manager=transaction_manager)

    with pytest.raises(MembershipNotFoundError):
        await sut.execute(_request(organization_id, invitation.id_))

    assert invitation.is_accepted is False
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
    invitation = _invitation(invitee=invitee, organization_id=organization_id)
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=invitee, repository=repository, transaction_manager=transaction_manager)
    if look_in_another_organization:
        request = _request(create_organization_id(), invitation.id_)
    else:
        request = _request(organization_id, OrganizationMembershipId(uuid4()))

    with pytest.raises(MembershipNotFoundError):
        await sut.execute(request)

    assert transaction_manager.commit_call_count == 0


# --- 5. Expired ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_expired_invitation_cannot_be_accepted() -> None:
    # 410 Gone: it existed, but can no longer be used. The row is left as it
    # is, so an ADMIN can re-invite and renew it.
    invitee = create_user()
    organization_id = create_organization_id()
    invitation = _invitation(
        invitee=invitee,
        organization_id=organization_id,
        expires_at=UtcDatetime(_NOW.value - timedelta(minutes=1)),
    )
    repository = _FakeOrganizationRepository(invitation)
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(caller=invitee, repository=repository, transaction_manager=transaction_manager)

    with pytest.raises(InvitationExpiredError):
        await sut.execute(_request(organization_id, invitation.id_))

    assert invitation.is_accepted is False
    assert transaction_manager.commit_call_count == 0


# --- 6. Unresolvable caller ---------------------------------------------------


@pytest.mark.asyncio
async def test_an_unresolvable_caller_is_refused_before_any_lookup() -> None:
    # A real CurrentUserService whose user lookup finds nothing (a deleted or
    # deactivated account) raises AuthorizationError itself.
    invitee = create_user()
    organization_id = create_organization_id()
    invitation = _invitation(invitee=invitee, organization_id=organization_id)
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
    assert transaction_manager.commit_call_count == 0
