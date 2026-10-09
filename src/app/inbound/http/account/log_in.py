from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, status

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.exceptions import BusinessTypeError
from app.core.queries.models.user import UserQm
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.exceptions import PasswordHasherBusyError
from app.outbound.auth_ctx.exceptions import AlreadyAuthenticatedError, AuthenticationError
from app.outbound.auth_ctx.handlers.log_in import LogIn, LogInRequest
from app.outbound.exceptions import StorageError

# Sample request bodies shown in Swagger (/docs); see sign_up.py for why the
# values are chosen by hand. Both log in as the seeded peter-parker
# (scripts/seed_db.py), so they work as-is against a seeded dev stack.
LOG_IN_EXAMPLES: Final[dict[str, Any]] = {
    "by_username": {
        "summary": "Log in with a username",
        "value": {"identifier": "peter-parker", "password": "SpideySense2024!"},
    },
    "by_email": {
        "summary": "Log in with an email address",
        "value": {"identifier": "peter.parker@dailybugle.com", "password": "SpideySense2024!"},
    },
}


def make_log_in_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/login/",
        error_map={
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            AlreadyAuthenticatedError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        },
        status_code=status.HTTP_200_OK,
        description=getdoc(LogIn),
    )
    @inject
    async def log_in(
        request: Annotated[LogInRequest, Body(openapi_examples=LOG_IN_EXAMPLES)],
        handler: FromDishka[LogIn],
    ) -> UserQm:
        return await handler.execute(request)

    return router
