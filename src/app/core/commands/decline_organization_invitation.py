import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.commands.organization_exceptions import MembershipNotFoundError
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembershipId

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclineOrganizationInvitationRequest:
    organization_id: UUID
    membership_id: UUID


class DeclineOrganizationInvitation:
    """
    - Only the invitee may decline their own invitation -- the same
      "is this invitation mine?" rule as AcceptOrganizationInvitation.
    - Declining DELETES the pending row, whether or not it has expired
      (clearing away a lapsed invitation is harmless). No clock is needed.
    - Only PENDING invitations can be declined. An accepted membership is
      reported as not found: leaving goes through RemoveOrganizationMember,
      which enforces that the last OWNER can never leave.
    - Missing, not yours, another organization's, or already accepted: all
      the same MembershipNotFoundError (404).
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        organization_repository: OrganizationRepository,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_user_service = current_user_service
        self._organization_repository = organization_repository
        self._transaction_manager = transaction_manager

    async def execute(self, request: DeclineOrganizationInvitationRequest) -> None:
        logger.info("Decline organization invitation: started.")

        # 1. Who is calling -- an unknown/inactive caller raises
        #    AuthorizationError here, before any lookup.
        current_user = await self._current_user_service.get_current_user()

        # 2. The caller's own PENDING invitation in this organization, or 404.
        membership = await self._organization_repository.get_membership_by_id(
            OrganizationId(request.organization_id),
            OrganizationMembershipId(request.membership_id),
        )
        if membership is None or membership.user_id != current_user.id_ or membership.is_accepted:
            raise MembershipNotFoundError

        # 3. Delete it -- staged, then committed once.
        await self._organization_repository.delete_membership(membership)
        await self._transaction_manager.commit()
        logger.info("Decline organization invitation: done.")
