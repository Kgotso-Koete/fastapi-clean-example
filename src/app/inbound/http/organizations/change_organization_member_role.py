from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict
from starlette import status

from app.core.commands.change_organization_member_role import (
    ChangeOrganizationMemberRole,
    ChangeOrganizationMemberRoleRequest,
)
from app.core.commands.organization_exceptions import (
    CannotGrantOwnerRoleError,
    CannotManageOwnerError,
    LastOwnerError,
    MembershipNotFoundError,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization_membership import OrganizationRole
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class ChangeOrganizationMemberRoleBody(BaseModel):
    """The request body: just the new role. An unknown value 422s here."""

    model_config = ConfigDict(frozen=True)

    role: OrganizationRole


def make_change_organization_member_role_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.patch(
        "/{organization_id}/members/{membership_id}/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # MembershipChecker's lookup failing.
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # A member below ADMIN (or an unknown/inactive caller).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # A non-OWNER granting OWNER, or changing an OWNER's role.
            CannotGrantOwnerRoleError: status.HTTP_403_FORBIDDEN,
            CannotManageOwnerError: status.HTTP_403_FORBIDDEN,
            # Not a member at all -- the organization's existence isn't revealed.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
            # No such membership in this organization.
            MembershipNotFoundError: status.HTTP_404_NOT_FOUND,
            # Demoting the last accepted OWNER.
            LastOwnerError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(ChangeOrganizationMemberRole),
    )
    @inject
    async def change_organization_member_role(
        organization_id: Annotated[UUID, Path()],
        membership_id: Annotated[UUID, Path()],
        body: ChangeOrganizationMemberRoleBody,
        interactor: FromDishka[ChangeOrganizationMemberRole],
    ) -> None:
        request = ChangeOrganizationMemberRoleRequest(
            organization_id=organization_id,
            membership_id=membership_id,
            role=body.role,
        )
        await interactor.execute(request)

    return router
