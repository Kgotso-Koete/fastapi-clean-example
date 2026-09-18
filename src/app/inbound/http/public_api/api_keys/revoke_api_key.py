from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Path, status
from fastapi.security import APIKeyHeader

from app.core.commands.api_key_exceptions import ApiKeyNotFoundError
from app.core.commands.revoke_api_key import RevokeApiKey, RevokeApiKeyRequest
from app.core.common.authorization.exceptions import AuthorizationError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME, ApiKeyAuthenticationError
from app.outbound.exceptions import StorageError


def make_revoke_api_key_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.delete(
        "/{api_key_id}/",
        error_map={
            ApiKeyAuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # 403, not 401, mirroring revoke_admin.py's own precedent --
            # AuthorizationError here can technically also originate from
            # CurrentUserService resolving a since-deactivated account
            # (which would arguably read better as 401), but RevokeApiKey
            # itself also raises this same, shared AuthorizationError
            # directly for the "not your key" ownership check, and the
            # plan calls for 403 on that case specifically. Unlike
            # ListApiKeys (which never raises AuthorizationError itself),
            # this route can't disambiguate the two sources by exception
            # type alone -- accepting that same ambiguity the private
            # app's admin routes already live with.
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            ApiKeyNotFoundError: status.HTTP_404_NOT_FOUND,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        # Documentation-only -- see account/profile.py's identical
        # declaration for the full reasoning (ApiKeyIdentityProvider reads
        # X-API-Key straight off the raw Request, not through this).
        dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False))],
        description=getdoc(RevokeApiKey),
    )
    @inject
    async def revoke_api_key(
        api_key_id: Annotated[UUID, Path()],
        interactor: FromDishka[RevokeApiKey],
    ) -> None:
        request = RevokeApiKeyRequest(api_key_id=api_key_id)
        await interactor.execute(request)

    return router
