import logging
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateOrganizationRequest:
    organization_id: UUID
    # None means "leave it as it is". Neither can be cleared: both are
    # mandatory, so an empty value fails validation instead.
    name: str | None = None
    description: str | None = None


class UpdateOrganizationResponse(TypedDict):
    id: UUID
    name: str
    description: str


class UpdateOrganization:
    """
    - Needs ADMIN (403 for a MEMBER, 404 for a non-member).
    - A partial update: a field left out stays as it is. Neither the name nor
      the description can be cleared.
    - Both values are validated before either changes, so an invalid
      description never leaves a half-applied rename behind.
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

    async def execute(self, request: UpdateOrganizationRequest) -> UpdateOrganizationResponse:
        logger.info("Update organization: started.")
        organization_id = OrganizationId(request.organization_id)

        # 1. ADMIN at least; a non-member gets 404 before any lookup.
        await self._current_organization_service.require_role(organization_id, OrganizationRole.ADMIN)

        # 2. require_role() just proved it exists, so None here means it was
        #    deleted concurrently -- still a plain 404, never a crash.
        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError

        # 3. Validate everything first (BusinessTypeError, 400), then change.
        name = OrganizationName(request.name) if request.name is not None else organization.name
        description = Description(request.description) if request.description is not None else organization.description
        organization.name = name
        organization.description = description

        # 4. The tracked entity's change is persisted by the commit.
        await self._transaction_manager.commit()
        logger.info("Update organization: done.")
        return UpdateOrganizationResponse(
            id=organization.id_,
            name=organization.name.value,
            description=organization.description.value,
        )
