from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Path
from starlette import status

from app.core.commands.decline_organization_invitation import (
    DeclineOrganizationInvitation,
    DeclineOrganizationInvitationRequest,
)
from app.core.commands.organization_exceptions import MembershipNotFoundError
from app.core.common.authorization.exceptions import AuthorizationError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import StorageError


def make_decline_organization_invitation_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/{organization_id}/members/{membership_id}/decline/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # An unknown/inactive caller (CurrentUserService).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # Missing, another organization's, not the caller's, or already
            # accepted -- all alike.
            MembershipNotFoundError: status.HTTP_404_NOT_FOUND,
        },
        status_code=status.HTTP_204_NO_CONTENT,
        description=getdoc(DeclineOrganizationInvitation),
    )
    @inject
    async def decline_organization_invitation(
        organization_id: Annotated[UUID, Path()],
        membership_id: Annotated[UUID, Path()],
        interactor: FromDishka[DeclineOrganizationInvitation],
    ) -> None:
        request = DeclineOrganizationInvitationRequest(organization_id=organization_id, membership_id=membership_id)
        await interactor.execute(request)

    return router
