from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path, status

from app.base.core.commands.exceptions import UserNotFoundError
from app.base.core.commands.revoke_admin import RevokeAdmin, RevokeAdminRequest
from app.base.core.common.authorization.exceptions import AuthorizationError
from app.base.inbound.http.errors.callbacks import log_info
from app.base.inbound.http.errors.router import make_error_aware_router
from app.base.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.base.outbound.auth_ctx.exceptions import AuthenticationError
from app.base.outbound.exceptions import StorageError


def make_revoke_admin_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.delete(
        "/{user_id}/roles/admin/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            UserNotFoundError: status.HTTP_404_NOT_FOUND,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(RevokeAdmin),
    )
    @inject
    async def revoke_admin(
        user_id: Annotated[UUID, Path()],
        interactor: FromDishka[RevokeAdmin],
    ) -> None:
        request = RevokeAdminRequest(user_id)
        await interactor.execute(request)

    return router
