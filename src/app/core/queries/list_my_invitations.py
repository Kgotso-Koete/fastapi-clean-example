import logging
from dataclasses import dataclass
from enum import StrEnum

from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.queries.ports.organization_reader import ListMyInvitationsQm, OrganizationReader
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams

logger = logging.getLogger(__name__)


class InvitationSortingField(StrEnum):
    CREATED_AT = "created_at"
    EXPIRES_AT = "expires_at"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMyInvitationsRequest:
    limit: int
    offset: int
    sorting_field: InvitationSortingField
    sorting_order: SortingOrder


class ListMyInvitations:
    """
    - Open to any authenticated caller.
    - Lists the caller's own PENDING, unexpired invitations, across every
      organization, with the ids the accept/decline routes need.
    - User-scoped, NOT organization-scoped: the invitee isn't a member yet,
      so an organization role check would reject them by definition.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        organization_reader: OrganizationReader,
    ) -> None:
        self._current_user_service = current_user_service
        self._organization_reader = organization_reader

    async def execute(self, request: ListMyInvitationsRequest) -> ListMyInvitationsQm:
        logger.info("List my invitations: started.")

        current_user = await self._current_user_service.get_current_user()
        invitations = await self._organization_reader.list_invitations_for_user(
            current_user.id_,
            pagination=OffsetPaginationParams(limit=request.limit, offset=request.offset),
            sorting=SortingParams(field=request.sorting_field, order=request.sorting_order),
        )

        logger.info("List my invitations: done.")
        return invitations
