from inspect import getdoc
from typing import Annotated, Any, Final
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Path
from pydantic import BaseModel, ConfigDict
from starlette import status

from app.core.commands.update_organization import (
    UpdateOrganization,
    UpdateOrganizationRequest,
    UpdateOrganizationResponse,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class UpdateOrganizationBody(BaseModel):
    """The request body. A field left out (or null) is left unchanged."""

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    description: str | None = None


# Sample request bodies shown in Swagger (/docs); see create_organization.py
# for why the values are chosen by hand. The first sets both fields (the
# checks need one example with every field); the second shows a field left
# out being left unchanged.
UPDATE_ORGANIZATION_EXAMPLES: Final[dict[str, Any]] = {
    "both_fields": {
        "summary": "Change the name and the description",
        "value": {"name": "Avengers", "description": "Earth's mightiest heroes, assembled."},
    },
    "description_only": {
        "summary": "Change only the description",
        "value": {"description": "Earth's mightiest heroes, assembled."},
    },
}


def make_update_organization_router() -> APIRouter:
    # Same shape as change_organization_member_role.py, one level up: the
    # organization itself, not one of its memberships.
    router = make_error_aware_router(on_error=log_info)

    @router.patch(
        "/{organization_id}/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # MembershipChecker's lookup failing.
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # A member below ADMIN (or an unknown/inactive caller).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # Not a member at all, or the organization is gone -- its
            # existence isn't revealed either way.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
            # OrganizationName's or Description's rules -- blank, too long,
            # disallowed characters, etc.
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_200_OK,
        description=getdoc(UpdateOrganization),
    )
    @inject
    async def update_organization(
        organization_id: Annotated[UUID, Path()],
        body: Annotated[UpdateOrganizationBody, Body(openapi_examples=UPDATE_ORGANIZATION_EXAMPLES)],
        interactor: FromDishka[UpdateOrganization],
    ) -> UpdateOrganizationResponse:
        request = UpdateOrganizationRequest(
            organization_id=organization_id,
            name=body.name,
            description=body.description,
        )
        return await interactor.execute(request)

    return router
