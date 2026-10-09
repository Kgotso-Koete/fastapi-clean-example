from inspect import getdoc
from typing import Annotated, Any, Final
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Path
from pydantic import BaseModel, ConfigDict
from starlette import status

from app.core.commands.invite_organization_member import (
    InviteOrganizationMember,
    InviteOrganizationMemberRequest,
    InviteOrganizationMemberResponse,
)
from app.core.commands.organization_exceptions import (
    CannotGrantOwnerRoleError,
    MembershipAlreadyExistsError,
    UnknownInviteeError,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class InviteOrganizationMemberBody(BaseModel):
    """The request body. The organization comes from the URL path, so only the
    invitee and their role are sent in the body."""

    model_config = ConfigDict(frozen=True)

    username: str
    role: OrganizationRole = OrganizationRole.MEMBER


# Sample request body shown in Swagger (/docs); see create_organization.py
# for why the values are chosen by hand. miles-morales is a seeded account
# (scripts/seed_db.py); role is "owner", "admin" or "member".
INVITE_ORGANIZATION_MEMBER_EXAMPLES: Final[dict[str, Any]] = {
    "invite_member": {
        "summary": "Invite a user as a member",
        "value": {"username": "miles-morales", "role": "member"},
    },
}


def make_invite_organization_member_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/{organization_id}/members/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # MembershipChecker's lookup failing.
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            # A member below ADMIN (or an unknown/inactive caller).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # A non-OWNER trying to grant OWNER.
            CannotGrantOwnerRoleError: status.HTTP_403_FORBIDDEN,
            # Not a member at all -- the organization's existence isn't revealed.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
            # No active account with that username.
            UnknownInviteeError: status.HTTP_404_NOT_FOUND,
            # Already a member, or already invited and not expired.
            MembershipAlreadyExistsError: status.HTTP_409_CONFLICT,
            # A username that breaks Username's own rules.
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_201_CREATED,
        description=getdoc(InviteOrganizationMember),
    )
    @inject
    async def invite_organization_member(
        organization_id: Annotated[UUID, Path()],
        body: Annotated[InviteOrganizationMemberBody, Body(openapi_examples=INVITE_ORGANIZATION_MEMBER_EXAMPLES)],
        interactor: FromDishka[InviteOrganizationMember],
    ) -> InviteOrganizationMemberResponse:
        request = InviteOrganizationMemberRequest(
            organization_id=organization_id,
            username=body.username,
            role=body.role,
        )
        return await interactor.execute(request)

    return router
