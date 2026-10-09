from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body
from starlette import status

from app.core.commands.create_organization import (
    CreateOrganization,
    CreateOrganizationRequest,
    CreateOrganizationResponse,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import StorageError

# Sample request body shown in Swagger (/docs), which developers copy. The
# schema only says "string", so the values are chosen by hand to pass core's
# OrganizationName (letters, digits and single spaces, hyphens or
# underscores between them) and Description rules; tests/sanity/inbound/http/
# checks the fields against the schema (docs/plans/15-upstream-autumn-2026.md,
# Step 5, item 10).
CREATE_ORGANIZATION_EXAMPLES: Final[dict[str, Any]] = {
    "new_organization": {
        "summary": "Create an organization",
        "value": {"name": "Fantastic Four", "description": "Marvel's first family of explorers."},
    },
}


def make_create_organization_router() -> APIRouter:
    # Same shape as users/create_user.py. No OrganizationNotFoundError
    # mapping here: creating an organization isn't scoped to an existing
    # one, so CurrentOrganizationService (the only raiser) is never involved.
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # An unknown/inactive current user (CurrentUserService).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # OrganizationName's or Description's rules -- blank, disallowed
            # characters, etc.
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_201_CREATED,
        description=getdoc(CreateOrganization),
    )
    @inject
    async def create_organization(
        request: Annotated[CreateOrganizationRequest, Body(openapi_examples=CREATE_ORGANIZATION_EXAMPLES)],
        interactor: FromDishka[CreateOrganization],
    ) -> CreateOrganizationResponse:
        return await interactor.execute(request)

    return router
