import logging
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.api_key import ApiKeyId
from app.core.common.exceptions import BaseError
from app.core.queries.ports.api_key_reader import ApiKeyReader, ApiKeyUsageStatsQm

logger = logging.getLogger(__name__)


class ApiKeyNotFoundError(BaseError):
    """
    Deliberately its own class, NOT reused from
    core/commands/api_key_exceptions.py's ApiKeyNotFoundError -- this is a
    query, and core.queries may never import core.commands (enforced by
    this project's lint-imports contract). Same message, same eventual
    HTTP mapping (404) as the command-side one; separate class purely for
    CQRS layering reasons.
    """

    default_message: ClassVar[str] = "API key not found."


@dataclass(frozen=True, slots=True)
class GetApiKeyUsageStatsRequest:
    api_key_id: UUID


class GetApiKeyUsageStats:
    """
    - Open to any authenticated caller.
    - Returns usage-analytics stats (use_count/last_used_at) for ONE of
      the caller's own API keys, by id.
    - By-id ownership-check convention, like RevokeApiKey -- not
      ListApiKeys's "scope the query itself" one -- since this looks up a
      single key by id rather than listing keys already scoped to the
      caller from the start.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        api_key_reader: ApiKeyReader,
    ) -> None:
        self._current_user_service = current_user_service
        self._api_key_reader = api_key_reader

    async def execute(self, request: GetApiKeyUsageStatsRequest) -> ApiKeyUsageStatsQm:
        logger.info("Get API key usage stats: started.")

        current_user = await self._current_user_service.get_current_user()
        api_key_id = ApiKeyId(request.api_key_id)
        # get_usage_stats_by_id() is a single-row lookup BY ID (same shape
        # as ApiKeyRepository.get_by_id()), so None here means "no ApiKey
        # row with this id exists" -- never "this key exists but has no
        # stats yet." use_count/last_used_at are plain columns on the same
        # row, initialized at issuance (0/None), so a brand-new, unused
        # key already returns a full, non-None ApiKeyUsageStatsQm.
        stats = await self._api_key_reader.get_usage_stats_by_id(api_key_id)
        if stats is None:
            raise ApiKeyNotFoundError

        if stats["user_id"] != current_user.id_:
            raise AuthorizationError

        logger.info("Get API key usage stats: done.")
        return stats
