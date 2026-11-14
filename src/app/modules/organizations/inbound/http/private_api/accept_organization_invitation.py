from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path
from starlette import status

from app.base.core.common.authorization.exceptions import AuthorizationError
from app.base.inbound.http.errors.callbacks import log_info
from app.base.inbound.http.errors.router import make_error_aware_router
from app.base.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.base.outbound.auth_ctx.exceptions import AuthenticationError
from app.base.outbound.exceptions import StorageError
from app.modules.organizations.core.commands.accept_organization_invitation import (
    AcceptOrganizationInvitation,
    AcceptOrganizationInvitationRequest,
)
from app.modules.organizations.core.commands.organization_exceptions import (
    InvitationExpiredError,
    MembershipNotFoundError,
)


def make_accept_organization_invitation_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/{organization_id}/members/{membership_id}/accept/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # An unknown/inactive caller (CurrentUserService).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # Missing, another organization's, or not the caller's -- all alike.
            MembershipNotFoundError: status.HTTP_404_NOT_FOUND,
            # It existed, but can no longer be used.
            InvitationExpiredError: status.HTTP_410_GONE,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(AcceptOrganizationInvitation),
    )
    @inject
    async def accept_organization_invitation(
        organization_id: Annotated[UUID, Path()],
        membership_id: Annotated[UUID, Path()],
        interactor: FromDishka[AcceptOrganizationInvitation],
    ) -> None:
        request = AcceptOrganizationInvitationRequest(organization_id=organization_id, membership_id=membership_id)
        await interactor.execute(request)

    return router
