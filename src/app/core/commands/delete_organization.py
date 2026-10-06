import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteOrganizationRequest:
    organization_id: UUID


class DeleteOrganization:
    """
    - Only an OWNER may delete the organization: an ADMIN or MEMBER gets 403,
      a non-member 404 (via CurrentOrganizationService).
    - Deletes the organization row only. Every membership and invitation goes
      with it through the database's ON DELETE CASCADE.
    - Irreversible: there is no soft delete.
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

    async def execute(self, request: DeleteOrganizationRequest) -> None:
        logger.info("Delete organization: started.")
        organization_id = OrganizationId(request.organization_id)

        # 1. OWNER only. An ADMIN can manage people but not end the
        #    organization; a non-member is told it doesn't exist (404).
        await self._current_organization_service.require_role(organization_id, OrganizationRole.OWNER)

        # 2. require_role() just proved it exists, so None here means it was
        #    deleted concurrently -- still a plain 404, never a crash.
        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError

        # 3. Stage the delete, then commit once. The cascade removes the
        #    memberships in the same statement, inside the same transaction.
        await self._organization_repository.delete(organization)
        await self._transaction_manager.commit()
        logger.info("Delete organization: done.")
