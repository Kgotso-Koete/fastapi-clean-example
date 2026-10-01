import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.commands.organization_exceptions import InvitationExpiredError, MembershipNotFoundError
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembershipId

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptOrganizationInvitationRequest:
    organization_id: UUID
    membership_id: UUID


class AcceptOrganizationInvitation:
    """
    - Only the invitee may accept their own invitation. Authorization is
      "is this invitation mine?" (the CanManageSelf shape), NOT
      CurrentOrganizationService -- the invitee isn't a member yet, so
      there's no role for MembershipChecker to find.
    - Someone else's invitation, an unknown id, or one from another
      organization all look the same: MembershipNotFoundError (404).
    - Idempotent: accepting an already-accepted membership changes nothing
      and commits nothing, so a retried request is safe (like RevokeApiKey).
    - An expired invitation can't be accepted: InvitationExpiredError (410).
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        organization_repository: OrganizationRepository,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_user_service = current_user_service
        self._organization_repository = organization_repository
        self._utc_timer = utc_timer
        self._transaction_manager = transaction_manager

    async def execute(self, request: AcceptOrganizationInvitationRequest) -> None:
        logger.info("Accept organization invitation: started.")

        # 1. Who is calling -- an unknown/inactive caller raises
        #    AuthorizationError here, before any lookup.
        current_user = await self._current_user_service.get_current_user()

        # 2. The invitation, scoped to the organization in the URL. Missing
        #    and "not yours" are the same 404 on purpose.
        membership = await self._organization_repository.get_membership_by_id(
            OrganizationId(request.organization_id),
            OrganizationMembershipId(request.membership_id),
        )
        if membership is None or membership.user_id != current_user.id_:
            raise MembershipNotFoundError

        # 3. Already a member: nothing to do. Checked before expiry, since an
        #    accepted membership has no expiry at all.
        if membership.is_accepted:
            logger.info("Accept organization invitation: already accepted, nothing to do.")
            return

        # 4. Too late -- the row stays so it can be renewed by a re-invite.
        now = self._utc_timer.now
        if membership.is_expired(now):
            raise InvitationExpiredError

        membership.accept(now=now)
        await self._transaction_manager.commit()
        logger.info("Accept organization invitation: done.")
