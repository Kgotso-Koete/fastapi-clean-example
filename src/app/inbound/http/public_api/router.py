from fastapi import APIRouter

from app.inbound.http.errors.openapi_responses import SERVER_ERROR_RESPONSES
from app.inbound.http.public_api.account.router import make_account_router
from app.inbound.http.public_api.api_keys.router import make_api_keys_router


def make_public_router() -> APIRouter:
    """
    No cookie_name param, unlike make_v1_router() -- this API never does
    cookie auth at all.
    """
    router = APIRouter(prefix="/v1", responses=SERVER_ERROR_RESPONSES)
    router.include_router(make_api_keys_router())
    router.include_router(make_account_router())
    return router
