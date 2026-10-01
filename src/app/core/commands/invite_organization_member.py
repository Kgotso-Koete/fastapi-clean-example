import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict
from uuid import UUID

from app.core.commands.organization_exceptions import (
    CannotGrantOwnerRoleError,
    MembershipAlreadyExistsError,
    UnknownInviteeError,
)
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent
from app.core.common.factories.organization_membership_id_factory import create_organization_membership_id
from app.core.common.ports.event_dispatcher import EventDispatcher
from app.core.common.ports.user_finder import UserFinder
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class InviteOrganizationMemberRequest:
    organization_id: UUID
    # The invitee's username -- invitations are only for existing accounts.
    username: str
    role: OrganizationRole = OrganizationRole.MEMBER


class InviteOrganizationMemberResponse(TypedDict):
    membership_id: UUID
    expires_at: datetime


class InviteOrganizationMember:
    """
    - Only an OWNER or ADMIN of the organization may invite; a MEMBER gets
      403, a non-member 404 (via CurrentOrganizationService).
    - Only an OWNER may invite someone AS an OWNER.
    - The invitee must be an existing, active account, found by username.
    - Creates a pending membership (accepted_at=None) that expires after
      invitation_ttl_days (ORGANIZATION_INVITATION_TTL_DAYS in production).
    - An invitee who already has a live row (a membership, or a pending
      invitation that hasn't expired) is a conflict. One whose only row is
      an EXPIRED invitation gets that same row renewed instead.
    - Both a new and a renewed invitation email the invitee, through an
      OrganizationInvitationCreatedEvent (SendOrganizationInvitationEmail).
    """

    def __init__(
        self,
        current_organization_service: CurrentOrganizationService,
        user_finder: UserFinder,
        organization_repository: OrganizationRepository,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
        invitation_ttl_days: int,
        event_dispatcher: EventDispatcher,
    ) -> None:
        self._current_organization_service = current_organization_service
        self._user_finder = user_finder
        self._organization_repository = organization_repository
        self._utc_timer = utc_timer
        self._transaction_manager = transaction_manager
        self._invitation_ttl_days = invitation_ttl_days
        self._event_dispatcher = event_dispatcher

    async def execute(self, request: InviteOrganizationMemberRequest) -> InviteOrganizationMemberResponse:
        logger.info("Invite organization member: started.")
        organization_id = OrganizationId(request.organization_id)

        # 1. The caller must be at least an ADMIN here (403/404 otherwise).
        #    Owner-only is checked next, which needs the caller's own role.
        _, inviter = await self._current_organization_service.require_role(organization_id, OrganizationRole.ADMIN)

        # 2. Granting OWNER needs the caller to be an OWNER themselves.
        #    require_role(OWNER) re-uses the same authorization path, at the
        #    cost of a second membership lookup, and only in this one case.
        if request.role == OrganizationRole.OWNER:
            await self._require_owner(organization_id)

        # 3. The invitee: an existing, ACTIVE account. Missing and inactive
        #    are deliberately the same error.
        invitee = await self._user_finder.find_by_username(Username(request.username))
        if invitee is None or not invitee.is_active:
            raise UnknownInviteeError

        now = self._utc_timer.now
        expires_at = UtcDatetime(now.value + timedelta(days=self._invitation_ttl_days))

        # 4. At most one row per (organization, user): conflict on a live row,
        #    renew an expired invitation in place, otherwise add a new one.
        existing = await self._organization_repository.get_membership_for_user(organization_id, invitee.id_)
        if existing is not None:
            if existing.is_accepted or not existing.is_expired(now):
                raise MembershipAlreadyExistsError
            existing.renew_invitation(
                role=request.role,
                invited_by_user_id=inviter.id_,
                now=now,
                expires_at=expires_at,
            )
            invitation = existing
        else:
            invitation = OrganizationMembership(
                id_=create_organization_membership_id(),
                organization_id=organization_id,
                user_id=invitee.id_,
                role=request.role,
                invited_by_user_id=inviter.id_,
                created_at=now,
                accepted_at=None,
                expires_at=expires_at,
            )
            self._organization_repository.add_membership(invitation)

        # 5. The invitation email. The organization's name is needed for it;
        #    require_role() above already proved the organization exists, so
        #    None here would mean it was deleted mid-request.
        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError
        invitation.record_event(
            OrganizationInvitationCreatedEvent(
                occurred_at=now.value,
                organization_id=organization_id,
                organization_name=organization.name.value,
                membership_id=invitation.id_,
                invitee_user_id=invitee.id_,
                invitee_email=invitee.email.value,
                inviter_username=inviter.username.value,
                role=invitation.role.value,
                expires_at=expires_at.value,
            )
        )
        # Staged BEFORE the commit, so the email's outbox row commits
        # atomically with the invitation; dispatched after, like CreateUser.
        events = invitation.collect_events()
        await self._event_dispatcher.stage(events)

        await self._transaction_manager.commit()
        await self._event_dispatcher.dispatch(events)

        logger.info("Invite organization member: done.")
        return InviteOrganizationMemberResponse(membership_id=invitation.id_, expires_at=expires_at.value)

    async def _require_owner(self, organization_id: OrganizationId) -> None:
        # Only AuthorizationError means "a member, but not an owner". Any other
        # failure (e.g. a StorageError from the membership lookup) must keep
        # its own meaning, not be disguised as a permissions problem.
        try:
            await self._current_organization_service.require_role(organization_id, OrganizationRole.OWNER)
        except AuthorizationError as e:
            raise CannotGrantOwnerRoleError from e
