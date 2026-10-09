from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Depends, status
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, ConfigDict

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.exceptions import PasswordHasherBusyError
from app.outbound.auth_ctx.exceptions import AuthenticationChangeError, AuthenticationError, ReAuthenticationError
from app.outbound.auth_ctx.handlers.change_password import ChangePassword, ChangePasswordRequest
from app.outbound.exceptions import StorageError


class ChangePasswordRequestSchema(BaseModel):
    """
    Using Pydantic model here is generally unnecessary.
    It's only implemented to render specific Swagger UI.
    """

    model_config = ConfigDict(frozen=True)

    current_password: str
    new_password: str


# Sample request body shown in Swagger (/docs); see sign_up.py for why the
# values are chosen by hand. The current password is the seeded
# peter-parker's (scripts/seed_db.py).
CHANGE_PASSWORD_EXAMPLES: Final[dict[str, Any]] = {
    "change_password": {
        "summary": "Change your own password",
        "value": {"current_password": "SpideySense2024!", "new_password": "SpideySense2025!"},
    },
}


def make_change_password_router(*, cookie_name: str) -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.put(
        "/password/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            AuthenticationChangeError: status.HTTP_400_BAD_REQUEST,
            ReAuthenticationError: status.HTTP_403_FORBIDDEN,
            PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(APIKeyCookie(name=cookie_name))],
        description=getdoc(ChangePassword),
    )
    @inject
    async def change_password(
        request_schema: Annotated[ChangePasswordRequestSchema, Body(openapi_examples=CHANGE_PASSWORD_EXAMPLES)],
        handler: FromDishka[ChangePassword],
    ) -> None:
        request = ChangePasswordRequest(
            current_password=request_schema.current_password,
            new_password=request_schema.new_password,
        )
        await handler.execute(request)

    return router
