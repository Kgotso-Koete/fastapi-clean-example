from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path, status

from app.base.core.commands.deactivate_user import DeactivateUser, DeactivateUserRequest
from app.base.core.commands.exceptions import UserNotFoundError
from app.base.core.common.authorization.exceptions import AuthorizationError
from app.base.inbound.http.errors.callbacks import log_info
from app.base.inbound.http.errors.router import make_error_aware_router
from app.base.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.base.outbound.auth_ctx.exceptions import AuthenticationError
from app.base.outbound.exceptions import StorageError


def make_deactivate_user_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.delete(
        "/{user_id}/activation/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            UserNotFoundError: status.HTTP_404_NOT_FOUND,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(DeactivateUser),
    )
    @inject
    async def deactivate_user(
        user_id: Annotated[UUID, Path()],
        interactor: FromDishka[DeactivateUser],
    ) -> None:
        request = DeactivateUserRequest(user_id)
        await interactor.execute(request)

    return router
