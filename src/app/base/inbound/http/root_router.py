from collections.abc import Sequence

from fastapi import APIRouter
from starlette.responses import RedirectResponse

from app.base.inbound.http.api_v1_router import make_v1_router
from app.base.inbound.http.debug.test_error import router as test_error_router
from app.base.inbound.http.health.router import make_health_router


def make_fastapi_root_router(*, debug_mode: bool, cookie_name: str, module_routers: Sequence[APIRouter]) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/",
        include_in_schema=False,
    )
    async def redirect_to_docs() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    router.include_router(make_health_router(debug_mode=debug_mode))
    router.include_router(make_v1_router(cookie_name=cookie_name, module_routers=module_routers))

    # Include test error endpoint for testing alerting (remove after testing)
    router.include_router(test_error_router, prefix="/debug", tags=["Debug"])

    return router
