from collections.abc import Sequence

from fastapi import APIRouter

from app.base.inbound.http.account.router import make_account_router
from app.base.inbound.http.errors.openapi_responses import SERVER_ERROR_RESPONSES
from app.base.inbound.http.users.router import make_users_router


def make_v1_router(*, cookie_name: str, module_routers: Sequence[APIRouter]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=SERVER_ERROR_RESPONSES)
    router.include_router(make_account_router(cookie_name=cookie_name))
    router.include_router(make_users_router(cookie_name=cookie_name))
    # The modules' private routers (docs/plans/16-modular-monolith.md, "The registry"):
    # base's inbound may not import a module (unit-order), so the composition root
    # builds them from the registered units and passes them in. They come after
    # base's own, in registration order, so the OpenAPI document keeps today's order.
    for module_router in module_routers:
        router.include_router(module_router)
    return router
