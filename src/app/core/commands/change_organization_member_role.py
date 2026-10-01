import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.commands.organization_exceptions import (
    CannotGrantOwnerRoleError,
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
from app.core.common.exceptions import BaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangeOrganizationMemberRoleRequest:
    organization_id: UUID
    membership_id: UUID
    role: OrganizationRole


class ChangeOrganizationMemberRole:
    """
    - Needs ADMIN (403 for a MEMBER, 404 for a non-member).
    - Only an OWNER may change an OWNER's role, or grant the OWNER role.
    - Demoting the last ACCEPTED owner is refused. Promoting someone else
      to OWNER first is how ownership is transferred.
    - Works on a pending invitation's role too, under the same rules.
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

    async def execute(self, request: ChangeOrganizationMemberRoleRequest) -> None:
        logger.info("Change organization member role: started.")
        organization_id = OrganizationId(request.organization_id)

        # 1. ADMIN at least; a non-member gets 404 before any lookup.
        await self._current_organization_service.require_role(organization_id, OrganizationRole.ADMIN)

        # 2. The target, scoped to THIS organization, or 404.
        target = await self._organization_repository.get_membership_by_id(
            organization_id,
            OrganizationMembershipId(request.membership_id),
        )
        if target is None:
            raise MembershipNotFoundError

        # 3. The OWNER role is the owner's to take away or hand out.
        if target.role == OrganizationRole.OWNER:
            await self._require_owner(organization_id, CannotManageOwnerError)
        elif request.role == OrganizationRole.OWNER:
            await self._require_owner(organization_id, CannotGrantOwnerRoleError)

        # 4. Never demote the last accepted owner.
        if (
            target.is_accepted
            and target.role == OrganizationRole.OWNER
            and request.role != OrganizationRole.OWNER
            and await self._organization_repository.count_owners(organization_id) <= 1
        ):
            raise LastOwnerError

        # 5. The tracked entity's change is persisted by the commit.
        target.role = request.role
        await self._transaction_manager.commit()
        logger.info("Change organization member role: done.")

    async def _require_owner(self, organization_id: OrganizationId, error: type[BaseError]) -> None:
        # Only "a member, but not an owner" becomes the given 403 error; any
        # other failure (e.g. a StorageError) keeps its own meaning.
        try:
            await self._current_organization_service.require_role(organization_id, OrganizationRole.OWNER)
        except AuthorizationError as e:
            raise error from e
