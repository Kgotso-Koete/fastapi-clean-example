from inspect import getdoc

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, status
from fastapi.security import APIKeyHeader

from app.core.queries.get_own_profile import GetOwnProfile
from app.core.queries.models.user import UserQm
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME, ApiKeyAuthenticationError
from app.outbound.exceptions import StorageError


def make_get_own_profile_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/profile/",
        error_map={
            ApiKeyAuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        },
        status_code=status.HTTP_200_OK,
        # Documentation-only -- ApiKeyIdentityProvider reads X-API-Key
        # straight off the raw Request, not through this dependency (its
        # return value is unused), so FastAPI/Swagger still has something
        # to introspect and render an X-API-Key field for. Mirrors the
        # private app's own APIKeyCookie declaration in this same file's
        # sibling (account/profile.py). auto_error=False keeps
        # ApiKeyIdentityProvider as the one and only source of 401s.
        dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False))],
        description=getdoc(GetOwnProfile),
    )
    @inject
    async def get_own_profile(interactor: FromDishka[GetOwnProfile]) -> UserQm:
        return await interactor.execute()

    return router
