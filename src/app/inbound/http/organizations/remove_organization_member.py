from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path
from starlette import status

from app.core.commands.organization_exceptions import (
    CannotManageOwnerError,
    LastOwnerError,
    MembershipNotFoundError,
)
from app.core.commands.remove_organization_member import (
    RemoveOrganizationMember,
    RemoveOrganizationMemberRequest,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


def make_remove_organization_member_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.delete(
        "/{organization_id}/members/{membership_id}/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # MembershipChecker's lookup failing.
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # A MEMBER removing someone else (or an unknown/inactive caller).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # An ADMIN removing an OWNER.
            CannotManageOwnerError: status.HTTP_403_FORBIDDEN,
            # Not a member at all -- the organization's existence isn't revealed.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
            # No such membership in this organization.
            MembershipNotFoundError: status.HTTP_404_NOT_FOUND,
            # The last accepted OWNER, including leaving.
            LastOwnerError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(RemoveOrganizationMember),
    )
    @inject
    async def remove_organization_member(
        organization_id: Annotated[UUID, Path()],
        membership_id: Annotated[UUID, Path()],
        interactor: FromDishka[RemoveOrganizationMember],
    ) -> None:
        request = RemoveOrganizationMemberRequest(organization_id=organization_id, membership_id=membership_id)
        await interactor.execute(request)

    return router
