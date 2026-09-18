from datetime import datetime
from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Path, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.queries.get_api_key_usage_stats import (
    ApiKeyNotFoundError,
    GetApiKeyUsageStats,
    GetApiKeyUsageStatsRequest,
)
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME, ApiKeyAuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class ApiKeyUsageStatsResponseSchema(BaseModel):
    """
    Deliberately omits user_id -- ApiKeyUsageStatsQm carries it only so
    GetApiKeyUsageStats can check ownership itself (see that port's own
    docstring); it must never be serialized back to the caller. key_hash
    was never selected by the reader in the first place, so there's
    nothing to omit for it here.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    key_prefix: str
    label: str | None
    use_count: int
    last_used_at: datetime | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


def make_get_api_key_usage_stats_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/{api_key_id}/usage/",
        error_map={
            ApiKeyAuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # 403, not 401 -- same reasoning as revoke_api_key.py's own
            # error_map comment: GetApiKeyUsageStats raises this same,
            # shared AuthorizationError directly for the "not your key"
            # ownership check, so this route accepts the same ambiguity
            # (vs. a since-deactivated account) the private app's admin
            # routes already live with.
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # This is core.queries.get_api_key_usage_stats.ApiKeyNotFoundError
            # -- a SEPARATE class from core.commands.api_key_exceptions's
            # ApiKeyNotFoundError, since core.queries may never import
            # core.commands. Same message, same 404 mapping, different
            # class for CQRS layering reasons only.
            ApiKeyNotFoundError: status.HTTP_404_NOT_FOUND,
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        },
        status_code=status.HTTP_200_OK,
        # Documentation-only -- see account/profile.py's identical
        # declaration for the full reasoning (ApiKeyIdentityProvider reads
        # X-API-Key straight off the raw Request, not through this).
        dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False))],
        description=getdoc(GetApiKeyUsageStats),
    )
    @inject
    async def get_api_key_usage_stats(
        api_key_id: Annotated[UUID, Path()],
        interactor: FromDishka[GetApiKeyUsageStats],
    ) -> ApiKeyUsageStatsResponseSchema:
        request = GetApiKeyUsageStatsRequest(api_key_id=api_key_id)
        stats = await interactor.execute(request)
        return ApiKeyUsageStatsResponseSchema(
            id=stats["id"],
            key_prefix=stats["key_prefix"],
            label=stats["label"],
            use_count=stats["use_count"],
            last_used_at=stats["last_used_at"],
            created_at=stats["created_at"],
            expires_at=stats["expires_at"],
            revoked_at=stats["revoked_at"],
        )

    return router
