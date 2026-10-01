import logging
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.queries.ports.organization_reader import ListOrganizationMembersQm, OrganizationReader
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams

logger = logging.getLogger(__name__)


class MemberSortingField(StrEnum):
    # Membership columns only -- the reader sorts on the memberships table,
    # so the joined username isn't a sort option.
    CREATED_AT = "created_at"
    ROLE = "role"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListOrganizationMembersRequest:
    organization_id: UUID
    limit: int
    offset: int
    sorting_field: MemberSortingField
    sorting_order: SortingOrder


class ListOrganizationMembers:
    """
    - Open to ANY member of the organization (the lowest role), not just
      an OWNER or ADMIN; a non-member gets 404 (via CurrentOrganizationService).
    - Lists every membership row, accepted and pending, with each member's
      username only -- never email or phone -- plus the member count.
    """

    def __init__(
        self,
        current_organization_service: CurrentOrganizationService,
        organization_reader: OrganizationReader,
    ) -> None:
        self._current_organization_service = current_organization_service
        self._organization_reader = organization_reader

    async def execute(self, request: ListOrganizationMembersRequest) -> ListOrganizationMembersQm:
        logger.info("List organization members: started.")
        organization_id = OrganizationId(request.organization_id)

        # Authorized BEFORE anything is read, so an outsider learns nothing.
        await self._current_organization_service.require_role(organization_id, OrganizationRole.MEMBER)
        members = await self._organization_reader.list_members(
            organization_id,
            pagination=OffsetPaginationParams(limit=request.limit, offset=request.offset),
            sorting=SortingParams(field=request.sorting_field, order=request.sorting_order),
        )

        logger.info("List organization members: done.")
        return members
