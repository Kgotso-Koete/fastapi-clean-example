import logging
from dataclasses import dataclass
from enum import StrEnum

from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.queries.ports.api_key_reader import ApiKeyReader, ListApiKeysQm
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams

logger = logging.getLogger(__name__)


class ApiKeySortingField(StrEnum):
    CREATED_AT = "created_at"
    EXPIRES_AT = "expires_at"
    LABEL = "label"


@dataclass(frozen=True, slots=True, kw_only=True)
class ListApiKeysRequest:
    limit: int
    offset: int
    sorting_field: ApiKeySortingField
    sorting_order: SortingOrder


class ListApiKeys:
    """
    - Open to any authenticated caller.
    - Retrieves a paginated list of the caller's OWN API keys only.
    - Same authorization shape as ChangePassword/ChangeOwnPassword's
      self-service pattern: no authorize() permission check -- scoped to
      current_user.id_ by construction, not by a rule that could be
      satisfied for someone else's keys.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        api_key_reader: ApiKeyReader,
    ) -> None:
        self._current_user_service = current_user_service
        self._api_key_reader = api_key_reader

    async def execute(self, request: ListApiKeysRequest) -> ListApiKeysQm:
        logger.info("List API keys: started.")

        current_user = await self._current_user_service.get_current_user()
        pagination = OffsetPaginationParams(limit=request.limit, offset=request.offset)
        sorting = SortingParams(field=request.sorting_field, order=request.sorting_order)
        api_keys = await self._api_key_reader.list_by_user(
            current_user.id_,
            pagination=pagination,
            sorting=sorting,
        )

        logger.info("List API keys: done.")
        return api_keys
