from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, status

from app.core.commands.exceptions import (
    EmailAlreadyExistsError,
    PhoneNumberAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.exceptions import BusinessTypeError
from app.core.queries.models.user import UserQm
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.exceptions import PasswordHasherBusyError
from app.outbound.auth_ctx.exceptions import AlreadyAuthenticatedError
from app.outbound.auth_ctx.handlers.sign_up import SignUp, SignUpRequest
from app.outbound.exceptions import StorageError

# Sample request bodies shown in Swagger (/docs), which developers copy. The
# schema only says "string", so these values are chosen by hand to pass the
# real rules in core's value objects (username 5-20 characters, password 12+
# with a letter, digit and symbol, a South African phone number), and
# tests/sanity/inbound/http/ checks their fields and types against the
# schema (docs/plans/15-upstream-autumn-2026.md, Step 5, item 10).
SIGN_UP_EXAMPLES: Final[dict[str, Any]] = {
    "new_user": {
        "summary": "Sign up a new user",
        "value": {
            "username": "kitty-pryde",
            "password": "PhaseShift2024!",
            "email": "kitty.pryde@xmen.org",
            "phone_number": "0821000016",
        },
    },
}


def make_sign_up_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/signup/",
        error_map={
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            AlreadyAuthenticatedError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            UsernameAlreadyExistsError: status.HTTP_409_CONFLICT,
            EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
            PhoneNumberAlreadyExistsError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_200_OK,
        description=getdoc(SignUp),
    )
    @inject
    async def sign_up(
        request: Annotated[SignUpRequest, Body(openapi_examples=SIGN_UP_EXAMPLES)],
        handler: FromDishka[SignUp],
    ) -> UserQm:
        return await handler.execute(request)

    return router
