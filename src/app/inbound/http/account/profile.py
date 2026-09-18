from inspect import getdoc

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, status
from fastapi.security import APIKeyCookie

from app.core.queries.get_own_profile import GetOwnProfile
from app.core.queries.models.user import UserQm
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import StorageError


def make_get_own_profile_router(*, cookie_name: str) -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/profile/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        },
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(APIKeyCookie(name=cookie_name))],
        description=getdoc(GetOwnProfile),
    )
    @inject
    async def get_own_profile(interactor: FromDishka[GetOwnProfile]) -> UserQm:
        return await interactor.execute()

    return router
