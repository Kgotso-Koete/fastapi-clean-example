import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.commands.organization_exceptions import (
    CannotManageOwnerError,
    LastOwnerError,
    MembershipNotFoundError,
)
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembershipId, OrganizationRole

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveOrganizationMemberRequest:
    organization_id: UUID
    membership_id: UUID


class RemoveOrganizationMember:
    """
    - Deletes a membership row, pending or accepted.
    - Removing YOURSELF is leaving: any member may leave.
    - Removing someone else needs ADMIN. Removing a pending row is how an
      admin revokes an invitation.
    - Only an OWNER may remove another OWNER (pending OWNER invites included).
    - The last ACCEPTED owner can never be removed, including by leaving.
    """

    def __init__(
        self,
        current_organization_service: CurrentOrganizationService,
        organization_repository: OrganizationRepository,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_organization_service = current_organization_service
        self._organization_repository = organization_repository
        self._transaction_manager = transaction_manager

    async def execute(self, request: RemoveOrganizationMemberRequest) -> None:
        logger.info("Remove organization member: started.")
        organization_id = OrganizationId(request.organization_id)

        # 1. Any member may get this far (leaving needs no more); a non-member
        #    gets 404 here, before the target is even looked up.
        _, caller = await self._current_organization_service.require_role(organization_id, OrganizationRole.MEMBER)

        # 2. The target, scoped to THIS organization, or 404.
        target = await self._organization_repository.get_membership_by_id(
            organization_id,
            OrganizationMembershipId(request.membership_id),
        )
        if target is None:
            raise MembershipNotFoundError

        # 3. Removing someone else: ADMIN at least, and OWNER for an owner.
        if target.user_id != caller.id_:
            await self._current_organization_service.require_role(organization_id, OrganizationRole.ADMIN)
            if target.role == OrganizationRole.OWNER:
                await self._require_owner(organization_id)

        # 4. Never leave the organization without an accepted owner.
        if (
            target.is_accepted
            and target.role == OrganizationRole.OWNER
            and await self._organization_repository.count_owners(organization_id) <= 1
        ):
            raise LastOwnerError

        # 5. Delete it -- staged, then committed once.
        await self._organization_repository.delete_membership(target)
        await self._transaction_manager.commit()
        logger.info("Remove organization member: done.")

    async def _require_owner(self, organization_id: OrganizationId) -> None:
        # Same narrow catch as InviteOrganizationMember._require_owner: only
        # "a member, but not an owner" becomes CannotManageOwnerError.
        try:
            await self._current_organization_service.require_role(organization_id, OrganizationRole.OWNER)
        except AuthorizationError as e:
            raise CannotManageOwnerError from e
