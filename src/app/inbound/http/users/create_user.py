from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body
from starlette import status

from app.core.commands.create_user import CreateUser, CreateUserRequest, CreateUserResponse
from app.core.commands.exceptions import (
    EmailAlreadyExistsError,
    PhoneNumberAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.exceptions import PasswordHasherBusyError
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import StorageError

# Sample request body shown in Swagger (/docs); see account/sign_up.py for why
# the values are chosen by hand. role is "user" or "admin"; only a super
# admin may create an admin.
CREATE_USER_EXAMPLES: Final[dict[str, Any]] = {
    "new_user": {
        "summary": "Create a user",
        "value": {
            "username": "sam-wilson",
            "email": "sam.wilson@avengers.org",
            "phone_number": "0821000017",
            "password": "OnYourLeft2024!",
            "role": "user",
        },
    },
}


def make_create_user_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            UsernameAlreadyExistsError: status.HTTP_409_CONFLICT,
            EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
            PhoneNumberAlreadyExistsError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_201_CREATED,
        description=getdoc(CreateUser),
    )
    @inject
    async def create_user(
        request: Annotated[CreateUserRequest, Body(openapi_examples=CREATE_USER_EXAMPLES)],
        interactor: FromDishka[CreateUser],
    ) -> CreateUserResponse:
        return await interactor.execute(request)

    return router
