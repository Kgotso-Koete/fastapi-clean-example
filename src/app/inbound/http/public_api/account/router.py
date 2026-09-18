from fastapi import APIRouter

from app.inbound.http.public_api.account.profile import make_get_own_profile_router


def make_account_router() -> APIRouter:
    router = APIRouter(prefix="/account", tags=["Account"])
    router.include_router(make_get_own_profile_router())
    return router
