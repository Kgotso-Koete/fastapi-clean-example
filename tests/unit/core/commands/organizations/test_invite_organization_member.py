from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.commands.invite_organization_member import (
    InviteOrganizationMember,
    InviteOrganizationMemberRequest,
)
from app.core.commands.organization_exceptions import (
    CannotGrantOwnerRoleError,
    MembershipAlreadyExistsError,
    UnknownInviteeError,
)
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.authorization.organization_ports import MembershipChecker
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.entities.user import User
from app.core.common.events.domain_event import DomainEvent
from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.ports.event_dispatcher import EventDispatcher
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager, FakeUserFinder, FakeUtcTimer
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_user

# InviteOrganizationMember (docs/plans/9-organizations.md, Step 6): an OWNER or
# ADMIN invites an EXISTING, active user by username. The invitation is a
# pending OrganizationMembership row (accepted_at=None) that expires after
# the configured TTL. Invitations are only for logged-in existing users --
# no email-address invites for people without an account.

_NOW = UtcDatetime(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
_DEFAULT_TTL_DAYS = 7


class _FakeMembershipChecker(MembershipChecker):
    """The CALLER's role in the organization (or None for a non-member) --
    what CurrentOrganizationService.require_role() authorizes against."""

    def __init__(self, role: OrganizationRole | None) -> None:
        self._role = role

    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        return self._role


class _FakeOrganizationRepository(OrganizationRepository):
    """get_membership_for_user() returns a fixed existing row (or None) --
    the INVITEE's current row in the organization, if any. get_by_id()
    returns the fixed organization, whose name the invitation email needs.
    Records every add_membership() call. Lookups this use case doesn't need
    raise NotImplementedError, so an unexpected call fails loudly."""

    def __init__(
        self,
        organization: Organization,
        existing_membership: OrganizationMembership | None = None,
    ) -> None:
        self._organization = organization
        self._existing_membership = existing_membership
        self.added_memberships: list[OrganizationMembership] = []

    def add(self, organization: Organization) -> None:
        raise NotImplementedError

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        return self._organization

    def add_membership(self, membership: OrganizationMembership) -> None:
        self.added_memberships.append(membership)

    async def get_membership_by_id(
        self,
        organization_id: OrganizationId,
        membership_id: OrganizationMembershipId,
    ) -> OrganizationMembership | None:
        raise NotImplementedError

    async def get_membership_for_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> OrganizationMembership | None:
        return self._existing_membership

    async def delete_membership(self, membership: OrganizationMembership) -> None:
        raise NotImplementedError

    async def count_owners(self, organization_id: OrganizationId) -> int:
        raise NotImplementedError


class _FakeEventDispatcher(EventDispatcher):
    """Records the events given to stage() and dispatch(), each with how many
    commits had happened at that moment -- so a test can prove stage() ran
    BEFORE the commit (the outbox row must commit with the invitation) and
    dispatch() AFTER it."""

    def __init__(self, transaction_manager: FakeTransactionManager) -> None:
        self._transaction_manager = transaction_manager
        self.staged: list[tuple[list[DomainEvent], int]] = []
        self.dispatched: list[tuple[list[DomainEvent], int]] = []

    async def stage(self, events: list[DomainEvent]) -> None:
        self.staged.append((events, self._transaction_manager.commit_call_count))

    async def dispatch(self, events: list[DomainEvent]) -> None:
        self.dispatched.append((events, self._transaction_manager.commit_call_count))


class _Harness:
    """Builds the use case with fakes and keeps them around for assertions,
    so each test only states what's different about its scenario."""

    def __init__(
        self,
        *,
        caller_role: OrganizationRole | None,
        invitee: User | None,
        existing_membership: OrganizationMembership | None = None,
        ttl_days: int = _DEFAULT_TTL_DAYS,
    ) -> None:
        self.caller = create_user()
        self.organization_id = create_organization_id()
        self.organization = Organization(
            id_=self.organization_id,
            name=OrganizationName("Avengers"),
            created_by_user_id=self.caller.id_,
            created_at=_NOW,
        )
        self.user_finder = FakeUserFinder(invitee)
        self.repository = _FakeOrganizationRepository(self.organization, existing_membership)
        self.transaction_manager = FakeTransactionManager()
        self.event_dispatcher = _FakeEventDispatcher(self.transaction_manager)
        self.sut = InviteOrganizationMember(
            current_organization_service=CurrentOrganizationService(
                current_user_service=create_current_user_service(self.caller),
                membership_checker=_FakeMembershipChecker(caller_role),
            ),
            user_finder=self.user_finder,
            organization_repository=self.repository,
            utc_timer=FakeUtcTimer(_NOW),
            transaction_manager=self.transaction_manager,
            # A plain int here, like IssueApiKey's max_keys_per_user -- in
            # production it comes from ORGANIZATION_INVITATION_TTL_DAYS
            # (whose env-var reading is proven by test_loader.py).
            invitation_ttl_days=ttl_days,
            event_dispatcher=self.event_dispatcher,
        )

    def request(self, username: str, role: OrganizationRole | None = None) -> InviteOrganizationMemberRequest:
        if role is None:
            return InviteOrganizationMemberRequest(organization_id=self.organization_id, username=username)
        return InviteOrganizationMemberRequest(organization_id=self.organization_id, username=username, role=role)

    def assert_nothing_written(self) -> None:
        assert self.repository.added_memberships == []
        assert self.transaction_manager.commit_call_count == 0
        # A rejected invitation sends no email either.
        assert self.event_dispatcher.staged == []
        assert self.event_dispatcher.dispatched == []


def _existing_membership(
    *,
    user: User,
    accepted: bool,
    expires_at: UtcDatetime | None = None,
) -> OrganizationMembership:
    # The invitee's pre-existing row in the SAME organization -- an accepted
    # membership, or a pending invitation (expired or not).
    return OrganizationMembership(
        id_=OrganizationMembershipId(uuid4()),
        organization_id=OrganizationId(uuid4()),
        user_id=user.id_,
        role=OrganizationRole.MEMBER,
        invited_by_user_id=UserId(uuid4()),
        created_at=UtcDatetime(_NOW.value - timedelta(days=30)),
        accepted_at=UtcDatetime(_NOW.value - timedelta(days=29)) if accepted else None,
        expires_at=None if accepted else expires_at,
    )


# --- 1. The happy path ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_role", [OrganizationRole.OWNER, OrganizationRole.ADMIN])
async def test_an_owner_or_admin_invites_an_active_user_as_a_pending_membership(
    caller_role: OrganizationRole,
) -> None:
    invitee = create_user()
    h = _Harness(caller_role=caller_role, invitee=invitee)

    response = await h.sut.execute(h.request(invitee.username.value, role=OrganizationRole.ADMIN))

    # The invitee was looked up by the username given.
    assert h.user_finder.find_by_username_calls == [Username(invitee.username.value)]
    # Exactly one pending row: the invitee, the chosen role, the caller as
    # inviter, in THIS organization -- committed once.
    assert len(h.repository.added_memberships) == 1
    invitation = h.repository.added_memberships[0]
    assert invitation.organization_id == h.organization_id
    assert invitation.user_id == invitee.id_
    assert invitation.role == OrganizationRole.ADMIN
    assert invitation.invited_by_user_id == h.caller.id_
    assert invitation.is_accepted is False
    assert invitation.created_at == _NOW
    assert invitation.expires_at == UtcDatetime(_NOW.value + timedelta(days=_DEFAULT_TTL_DAYS))
    assert h.transaction_manager.commit_call_count == 1
    # The response identifies the invitation and says when it lapses.
    assert response["membership_id"] == invitation.id_
    assert response["expires_at"] == invitation.expires_at.value


# --- 2. Default role --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_role_defaults_to_member_when_none_is_given() -> None:
    invitee = create_user()
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee)

    await h.sut.execute(h.request(invitee.username.value))

    assert h.repository.added_memberships[0].role == OrganizationRole.MEMBER


# --- 3 & 4. Who may invite ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_member_cannot_invite() -> None:
    # A real member, but below ADMIN -- 403, not 404: they already know the
    # organization exists.
    invitee = create_user()
    h = _Harness(caller_role=OrganizationRole.MEMBER, invitee=invitee)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(h.request(invitee.username.value))

    h.assert_nothing_written()


@pytest.mark.asyncio
async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    invitee = create_user()
    h = _Harness(caller_role=None, invitee=invitee)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request(invitee.username.value))

    h.assert_nothing_written()


# --- 5. Who may be invited --------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invitee",
    [
        pytest.param(None, id="unknown_username"),
        pytest.param(create_user(is_active=False), id="inactive_account"),
    ],
)
async def test_an_unknown_or_inactive_invitee_is_rejected(invitee: User | None) -> None:
    # Both give the same error -- an inactive account is treated as if it
    # doesn't exist, so an invite can't be used to probe account state.
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee)

    with pytest.raises(UnknownInviteeError):
        await h.sut.execute(h.request("some_username"))

    h.assert_nothing_written()


# --- 6. Granting OWNER ------------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_cannot_invite_someone_as_owner() -> None:
    # apptension/saas-boilerplate's rule: only an existing OWNER may grant
    # the OWNER role. An ADMIN may still invite another ADMIN (test 1).
    invitee = create_user()
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee)

    with pytest.raises(CannotGrantOwnerRoleError):
        await h.sut.execute(h.request(invitee.username.value, role=OrganizationRole.OWNER))

    h.assert_nothing_written()


@pytest.mark.asyncio
async def test_an_owner_can_invite_someone_as_owner() -> None:
    invitee = create_user()
    h = _Harness(caller_role=OrganizationRole.OWNER, invitee=invitee)

    await h.sut.execute(h.request(invitee.username.value, role=OrganizationRole.OWNER))

    assert h.repository.added_memberships[0].role == OrganizationRole.OWNER


# --- 7 & 8. An invitee who already has a row ----------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "accepted",
    [
        pytest.param(True, id="already_a_member"),
        pytest.param(False, id="already_invited_and_not_expired"),
    ],
)
async def test_inviting_someone_who_already_has_a_live_row_is_a_conflict(accepted: bool) -> None:
    # Checked BEFORE insert, so the unique (organization_id, user_id)
    # constraint never surfaces as a raw IntegrityError.
    invitee = create_user()
    existing = _existing_membership(
        user=invitee,
        accepted=accepted,
        expires_at=UtcDatetime(_NOW.value + timedelta(days=1)),
    )
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee, existing_membership=existing)

    with pytest.raises(MembershipAlreadyExistsError):
        await h.sut.execute(h.request(invitee.username.value))

    h.assert_nothing_written()


@pytest.mark.asyncio
async def test_re_inviting_over_an_expired_invitation_refreshes_that_same_row() -> None:
    # The unique constraint rules out a second row, and a lapsed invitation
    # shouldn't block a fresh one -- so the SAME row is renewed in place:
    # new role, new inviter, new created_at, new expires_at.
    invitee = create_user()
    expired = _existing_membership(
        user=invitee,
        accepted=False,
        expires_at=UtcDatetime(_NOW.value - timedelta(days=1)),
    )
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee, existing_membership=expired)

    response = await h.sut.execute(h.request(invitee.username.value, role=OrganizationRole.ADMIN))

    # No second row -- the existing (tracked) one was changed and committed.
    assert h.repository.added_memberships == []
    assert h.transaction_manager.commit_call_count == 1
    assert expired.role == OrganizationRole.ADMIN
    assert expired.invited_by_user_id == h.caller.id_
    assert expired.created_at == _NOW
    assert expired.expires_at == UtcDatetime(_NOW.value + timedelta(days=_DEFAULT_TTL_DAYS))
    assert expired.is_accepted is False
    assert response["membership_id"] == expired.id_


# --- 9. The TTL is configurable -----------------------------------------------


@pytest.mark.asyncio
async def test_the_invitation_expires_after_the_configured_ttl() -> None:
    invitee = create_user()
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee, ttl_days=3)

    await h.sut.execute(h.request(invitee.username.value))

    assert h.repository.added_memberships[0].expires_at == UtcDatetime(_NOW.value + timedelta(days=3))


# --- 10. The invitation email (Step 6b) -----------------------------------------


def _single_event(h: _Harness) -> OrganizationInvitationCreatedEvent:
    # Exactly one event, staged BEFORE the commit (so its outbox row commits
    # atomically with the invitation) and dispatched AFTER it -- the same
    # stage/commit/dispatch order CreateUser uses for the welcome email.
    assert len(h.event_dispatcher.staged) == 1
    assert len(h.event_dispatcher.dispatched) == 1
    staged_events, commits_before_stage = h.event_dispatcher.staged[0]
    dispatched_events, commits_before_dispatch = h.event_dispatcher.dispatched[0]
    assert commits_before_stage == 0
    assert commits_before_dispatch == 1
    assert staged_events == dispatched_events
    assert len(staged_events) == 1
    event = staged_events[0]
    assert isinstance(event, OrganizationInvitationCreatedEvent)
    return event


@pytest.mark.asyncio
async def test_inviting_records_an_invitation_created_event_for_the_email() -> None:
    invitee = create_user()
    h = _Harness(caller_role=OrganizationRole.OWNER, invitee=invitee)

    response = await h.sut.execute(h.request(invitee.username.value, role=OrganizationRole.ADMIN))

    event = _single_event(h)
    # Everything the email needs, so the handler never queries the database.
    assert event.occurred_at == _NOW.value
    assert event.organization_id == h.organization_id
    assert event.organization_name == "Avengers"
    assert event.membership_id == response["membership_id"]
    assert event.invitee_user_id == invitee.id_
    assert event.invitee_email == invitee.email.value
    assert event.inviter_username == h.caller.username.value
    assert event.role == "admin"
    assert event.expires_at == response["expires_at"]


@pytest.mark.asyncio
async def test_renewing_an_expired_invitation_emails_the_invitee_again() -> None:
    # A renewed invitation is a fresh offer, with a new expiry -- the invitee
    # needs to hear about it just like a first invitation.
    invitee = create_user()
    expired = _existing_membership(
        user=invitee,
        accepted=False,
        expires_at=UtcDatetime(_NOW.value - timedelta(days=1)),
    )
    h = _Harness(caller_role=OrganizationRole.ADMIN, invitee=invitee, existing_membership=expired)

    await h.sut.execute(h.request(invitee.username.value))

    event = _single_event(h)
    assert event.membership_id == expired.id_
    assert event.expires_at == UtcDatetime(_NOW.value + timedelta(days=_DEFAULT_TTL_DAYS)).value
