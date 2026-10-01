import logging
from dataclasses import dataclass
from enum import StrEnum

from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.queries.ports.organization_reader import ListMyOrganizationsQm, OrganizationReader
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams

logger = logging.getLogger(__name__)


class OrganizationSortingField(StrEnum):
    CREATED_AT = "created_at"
    NAME = "name"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMyOrganizationsRequest:
    limit: int
    offset: int
    sorting_field: OrganizationSortingField
    sorting_order: SortingOrder


class ListMyOrganizations:
    """
    - Open to any authenticated caller.
    - Lists the organizations the caller has an ACCEPTED membership in, with
      their own role and each organization's member count.
    - User-scoped, like ListApiKeys: scoped to the caller's id by
      construction, so no organization-scoped role check is needed.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        organization_reader: OrganizationReader,
    ) -> None:
        self._current_user_service = current_user_service
        self._organization_reader = organization_reader

    async def execute(self, request: ListMyOrganizationsRequest) -> ListMyOrganizationsQm:
        logger.info("List my organizations: started.")

        current_user = await self._current_user_service.get_current_user()
        organizations = await self._organization_reader.list_for_user(
            current_user.id_,
            pagination=OffsetPaginationParams(limit=request.limit, offset=request.offset),
            sorting=SortingParams(field=request.sorting_field, order=request.sorting_order),
        )

        logger.info("List my organizations: done.")
        return organizations
