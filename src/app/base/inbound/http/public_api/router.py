from collections.abc import Sequence

from fastapi import APIRouter

from app.base.inbound.http.errors.openapi_responses import SERVER_ERROR_RESPONSES
from app.base.inbound.http.public_api.account.router import make_account_router
from app.base.inbound.http.public_api.api_keys.router import make_api_keys_router


def make_public_router(*, module_routers: Sequence[APIRouter]) -> APIRouter:
    """
    No cookie_name param, unlike make_v1_router() -- this API never does
    cookie auth at all.
    """
    router = APIRouter(prefix="/v1", responses=SERVER_ERROR_RESPONSES)
    router.include_router(make_api_keys_router())
    router.include_router(make_account_router())
    # The modules' public routers (docs/plans/16-modular-monolith.md, "The registry"):
    # base's inbound may not import a module (unit-order), so the composition root
    # builds them from the registered units and passes them in, after base's own.
    for module_router in module_routers:
        router.include_router(module_router)
    return router
