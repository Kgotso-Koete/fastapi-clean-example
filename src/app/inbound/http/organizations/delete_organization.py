from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path
from starlette import status

from app.core.commands.delete_organization import DeleteOrganization, DeleteOrganizationRequest
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


def make_delete_organization_router() -> APIRouter:
    # Same shape as remove_organization_member.py, one level up: the
    # organization itself, not one of its memberships.
    router = make_error_aware_router(on_error=log_info)

    @router.delete(
        "/{organization_id}/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # MembershipChecker's lookup failing.
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # An ADMIN or MEMBER -- only an OWNER may delete (or an
            # unknown/inactive caller).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # Not a member at all, or the organization is already gone -- its
            # existence isn't revealed either way.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(DeleteOrganization),
    )
    @inject
    async def delete_organization(
        organization_id: Annotated[UUID, Path()],
        interactor: FromDishka[DeleteOrganization],
    ) -> None:
        await interactor.execute(DeleteOrganizationRequest(organization_id=organization_id))

    return router
