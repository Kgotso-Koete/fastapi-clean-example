from fastapi import APIRouter, FastAPI

from app.base.inbound.http.api_v1_router import make_v1_router


def _paths(router: APIRouter) -> list[str]:
    # Every path the router serves, in include order, read the way a client sees
    # them: from the OpenAPI document of an app that includes the router (what
    # Swagger and the snapshot tests read). Not from router.routes, whose contents
    # are FastAPI's internal business: in FastAPI 0.142 they held no APIRoute for
    # an included router's endpoints, so the paths came back empty.
    app = FastAPI()
    app.include_router(router)
    return list(app.openapi()["paths"])


def test_includes_the_module_routers_it_is_given_after_bases_own() -> None:
    # base's inbound may not import a module (plan 16, unit-order), so the
    # modules' routers arrive from the composition root. They come after
    # base's own routers, the order today's OpenAPI documents show.
    widgets = APIRouter(prefix="/widgets")

    @widgets.get("/")
    async def list_widgets() -> None: ...

    paths = _paths(make_v1_router(cookie_name="session", module_routers=(widgets,)))

    assert paths[-1] == "/api/v1/widgets/"


def test_serves_no_module_routes_when_given_none() -> None:
    # Organizations' routes come only from the registry: with no module
    # routers, none of them is served (plan 16, user story 4).
    paths = _paths(make_v1_router(cookie_name="session", module_routers=()))

    # base's own routes are still served, so the check below can't pass on an empty list.
    assert "/api/v1/users/" in paths
    assert not [path for path in paths if path.startswith("/api/v1/organizations")]
