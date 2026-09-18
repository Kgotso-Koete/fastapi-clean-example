from abc import abstractmethod
from datetime import datetime
from typing import Protocol, TypedDict
from uuid import UUID

from app.core.common.entities.api_key import ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingParams


class ApiKeyQm(TypedDict):
    id: UUID
    key_prefix: str  # e.g. "ak_a1b2c3d4" -- enough to tell keys apart, never the secret
    label: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class ListApiKeysQm(TypedDict):
    api_keys: list[ApiKeyQm]
    total: int
    limit: int
    offset: int


class ApiKeyUsageStatsQm(TypedDict):
    id: UUID
    # Not returned to the caller (stripped by the HTTP response schema) --
    # present only so GetApiKeyUsageStats can check ownership itself,
    # mirroring how RevokeApiKey checks ownership after an unscoped load.
    user_id: UUID
    key_prefix: str
    label: str | None
    use_count: int
    last_used_at: datetime | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class ApiKeyReader(Protocol):
    @abstractmethod
    async def list_by_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListApiKeysQm: ...

    @abstractmethod
    async def get_usage_stats_by_id(self, api_key_id: ApiKeyId) -> ApiKeyUsageStatsQm | None:
        """
        Deliberately unscoped by user_id (unlike list_by_user) -- mirrors
        ApiKeyRepository.get_by_id()'s shape, so GetApiKeyUsageStats can
        raise the same 404-vs-403 distinction RevokeApiKey already
        establishes for by-id access to someone else's key, rather than
        folding both cases into one 404.
        """
        ...
