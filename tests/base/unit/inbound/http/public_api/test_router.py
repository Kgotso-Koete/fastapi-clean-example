from fastapi import APIRouter, FastAPI

from app.base.inbound.http.public_api.router import make_public_router


def _paths(router: APIRouter) -> list[str]:
    # Every path the router serves, in include order, read from the OpenAPI
    # document of an app that includes it (tests/base/unit/inbound/http/
    # test_api_v1_router.py says why not router.routes). The public app is
    # mounted at /public, so these paths start at /v1.
    app = FastAPI()
    app.include_router(router)
    return list(app.openapi()["paths"])


def test_includes_the_module_routers_it_is_given_after_bases_own() -> None:
    # base's inbound may not import a module (plan 16, unit-order), so the
    # modules' public routers arrive from the composition root. They come
    # after base's own (API keys, then account), the order today's public
    # OpenAPI document shows.
    widgets = APIRouter(prefix="/widgets")

    @widgets.get("/")
    async def list_widgets() -> None: ...

    paths = _paths(make_public_router(module_routers=(widgets,)))

    assert paths[-1] == "/v1/widgets/"


def test_serves_no_module_routes_when_given_none() -> None:
    # Organizations' public routes come only from the registry: with no module
    # routers, none of them is served (plan 16, user story 4).
    paths = _paths(make_public_router(module_routers=()))

    # base's own routes are still served, so the check below can't pass on an empty list.
    assert "/v1/account/profile/" in paths
    assert not [path for path in paths if path.startswith("/v1/organizations")]
