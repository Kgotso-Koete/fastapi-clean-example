from fastapi import APIRouter

from app.inbound.http.public_api.organizations.list_my_organizations import make_list_my_organizations_router
from app.inbound.http.public_api.organizations.list_organization_members import (
    make_list_organization_members_router,
)


def make_organizations_router() -> APIRouter:
    # Read-only on purpose (docs/plans/9-organizations.md, Step 15): API keys
    # are per-user, so a leaked key would carry its owner's powers in every
    # organization they belong to. Organization writes, and ListMyInvitations,
    # stay on the cookie app until API keys can be scoped.
    router = APIRouter(prefix="/organizations", tags=["Organizations"])
    router.include_router(make_list_my_organizations_router())
    router.include_router(make_list_organization_members_router())
    return router
