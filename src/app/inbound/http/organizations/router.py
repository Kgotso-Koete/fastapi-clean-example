from fastapi import APIRouter, Depends
from fastapi.security import APIKeyCookie

from app.inbound.http.organizations.accept_organization_invitation import make_accept_organization_invitation_router
from app.inbound.http.organizations.change_organization_member_role import (
    make_change_organization_member_role_router,
)
from app.inbound.http.organizations.create_organization import make_create_organization_router
from app.inbound.http.organizations.decline_organization_invitation import make_decline_organization_invitation_router
from app.inbound.http.organizations.delete_organization import make_delete_organization_router
from app.inbound.http.organizations.invite_organization_member import make_invite_organization_member_router
from app.inbound.http.organizations.list_my_invitations import make_list_my_invitations_router
from app.inbound.http.organizations.list_my_organizations import make_list_my_organizations_router
from app.inbound.http.organizations.list_organization_members import make_list_organization_members_router
from app.inbound.http.organizations.remove_organization_member import make_remove_organization_member_router
from app.inbound.http.organizations.update_organization import make_update_organization_router


def make_organizations_router(*, cookie_name: str) -> APIRouter:
    # Same shape as users/router.py: cookie-authenticated, one sub-router
    # per use case, grown one route at a time as each plan step lands.
    router = APIRouter(
        prefix="/organizations",
        tags=["Organizations"],
        dependencies=[Depends(APIKeyCookie(name=cookie_name))],
    )
    router.include_router(make_create_organization_router())
    router.include_router(make_invite_organization_member_router())
    router.include_router(make_accept_organization_invitation_router())
    router.include_router(make_decline_organization_invitation_router())
    router.include_router(make_remove_organization_member_router())
    router.include_router(make_change_organization_member_role_router())
    router.include_router(make_list_my_organizations_router())
    router.include_router(make_list_my_invitations_router())
    router.include_router(make_list_organization_members_router())
    router.include_router(make_delete_organization_router())
    router.include_router(make_update_organization_router())
    return router
