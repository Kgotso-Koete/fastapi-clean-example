from inspect import getdoc
from typing import Annotated, Any, Final
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Path
from pydantic import BaseModel, ConfigDict
from pydantic.experimental.missing_sentinel import MISSING
from starlette import status

from app.core.commands.exceptions import (
    EmailAlreadyExistsError,
    PhoneNumberAlreadyExistsError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from app.core.commands.update_user_profile import (
    UpdateUserProfile,
    UpdateUserProfileRequest,
    UpdateUserProfileResponse,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.inbound.missing import omit_if_missing
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import StorageError


class UpdateUserProfileRequestSchema(BaseModel):
    """
    Using Pydantic model here is generally unnecessary.
    It's only implemented to render specific Swagger UI.

    A field left out is MISSING (pydantic's "not sent" sentinel), turned into
    core's OMITTED before the command sees it, so a PATCH changes only what's
    sent; the description alone can also be null, which clears it
    (docs/plans/10-profile-editing.md, decision 3).
    """

    model_config = ConfigDict(frozen=True)

    username: str | MISSING = MISSING
    email: str | MISSING = MISSING
    phone_number: str | MISSING = MISSING
    description: str | MISSING | None = MISSING


# Sample request bodies shown in Swagger (/docs); see account/sign_up.py for
# why the values are chosen by hand. The first fills every field, for a USER an
# admin manages; the second shows that null clears the description.
UPDATE_USER_PROFILE_EXAMPLES: Final[dict[str, Any]] = {
    "edit_profile": {
        "summary": "Edit another user's profile",
        "value": {
            "username": "spider-man",
            "email": "spidey@example.com",
            "phone_number": "0821000099",
            "description": "Edited by an admin.",
        },
    },
    "clear_description": {
        "summary": "Clear another user's description",
        "value": {"description": None},
    },
}


def make_update_user_profile_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.patch(
        "/{user_id}/profile/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            UserNotFoundError: status.HTTP_404_NOT_FOUND,
            UsernameAlreadyExistsError: status.HTTP_409_CONFLICT,
            EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
            PhoneNumberAlreadyExistsError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_200_OK,
        description=getdoc(UpdateUserProfile),
    )
    @inject
    async def update_user_profile(
        user_id: Annotated[UUID, Path()],
        request_schema: Annotated[
            UpdateUserProfileRequestSchema,
            Body(openapi_examples=UPDATE_USER_PROFILE_EXAMPLES),
        ],
        interactor: FromDishka[UpdateUserProfile],
    ) -> UpdateUserProfileResponse:
        request = UpdateUserProfileRequest(
            user_id=user_id,
            username=omit_if_missing(request_schema.username),
            email=omit_if_missing(request_schema.email),
            phone_number=omit_if_missing(request_schema.phone_number),
            description=omit_if_missing(request_schema.description),
        )
        return await interactor.execute(request)

    return router
