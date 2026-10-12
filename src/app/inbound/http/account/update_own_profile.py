from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Depends, status
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, ConfigDict
from pydantic.experimental.missing_sentinel import MISSING

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
from app.inbound.missing import omit_if_missing
from app.outbound.adapters.exceptions import PasswordHasherBusyError
from app.outbound.auth_ctx.exceptions import AuthenticationError, ReAuthenticationError
from app.outbound.auth_ctx.handlers.update_own_profile import UpdateOwnProfile, UpdateOwnProfileRequest
from app.outbound.exceptions import StorageError


class UpdateOwnProfileRequestSchema(BaseModel):
    """
    Using Pydantic model here is generally unnecessary.
    It's only implemented to render specific Swagger UI.

    A field left out is MISSING (pydantic's "not sent" sentinel), turned into
    core's OMITTED before the handler sees it, so a PATCH changes only what's
    sent; the description alone can also be null, which clears it
    (docs/plans/10-profile-editing.md, decision 3).
    """

    model_config = ConfigDict(frozen=True)

    username: str | MISSING = MISSING
    email: str | MISSING = MISSING
    phone_number: str | MISSING = MISSING
    description: str | MISSING | None = MISSING
    current_password: str | None = None


# Sample request bodies shown in Swagger (/docs); see sign_up.py for why the
# values are chosen by hand. The first fills every field, as the seeded
# peter-parker (scripts/seed_db.py), whose real password a changed email
# needs; the second shows that null clears the description.
UPDATE_OWN_PROFILE_EXAMPLES: Final[dict[str, Any]] = {
    "update_profile": {
        "summary": "Edit your own profile",
        "value": {
            "username": "spider-man",
            "email": "spidey@example.com",
            "phone_number": "0821000099",
            "description": "Your friendly neighborhood Spider-Man.",
            "current_password": "SpideySense2024!",
        },
    },
    "clear_description": {
        "summary": "Clear your description",
        "value": {"description": None},
    },
}


def make_update_own_profile_router(*, cookie_name: str) -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.patch(
        "/profile/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            # A changed email without the right current password, as
            # PUT /account/password/ answers a wrong one.
            ReAuthenticationError: status.HTTP_403_FORBIDDEN,
            PasswordHasherBusyError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            UsernameAlreadyExistsError: status.HTTP_409_CONFLICT,
            EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
            PhoneNumberAlreadyExistsError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(APIKeyCookie(name=cookie_name))],
        description=getdoc(UpdateOwnProfile),
    )
    @inject
    async def update_own_profile(
        request_schema: Annotated[
            UpdateOwnProfileRequestSchema,
            Body(openapi_examples=UPDATE_OWN_PROFILE_EXAMPLES),
        ],
        handler: FromDishka[UpdateOwnProfile],
    ) -> UserQm:
        request = UpdateOwnProfileRequest(
            username=omit_if_missing(request_schema.username),
            email=omit_if_missing(request_schema.email),
            phone_number=omit_if_missing(request_schema.phone_number),
            description=omit_if_missing(request_schema.description),
            current_password=request_schema.current_password,
        )
        return await handler.execute(request)

    return router
