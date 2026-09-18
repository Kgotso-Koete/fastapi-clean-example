from typing import Final

import asgi_lifespan
import httpx2
import pytest
from fastapi import FastAPI

from app.main.config.settings import AppSettings
from app.main.run_public_api import make_app_with_public_api
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME

_STARTUP_TIMEOUT_S = 30

# Every public-API route that authenticates via ApiKeyIdentityProvider
# (issue_api_key.py is deliberately excluded -- it's the "prove who you are
# via the request body" route, no header auth at all).
_API_KEY_AUTHENTICATED_ROUTES: Final[list[tuple[str, str]]] = [
    ("get", "/v1/account/profile/"),
    ("get", "/v1/api-keys/"),
    ("delete", "/v1/api-keys/{api_key_id}/"),
    ("get", "/v1/api-keys/{api_key_id}/usage/"),
]


@pytest.fixture
def it_combined_app() -> FastAPI:
    # ENVIRONMENT="production" specifically -- proves /public/docs stays
    # reachable regardless of the private app's own ENVIRONMENT-gated
    # /docs (see make_app()'s docs_reachable logic in main/run.py), which
    # is the entire point of this feature.
    return make_app_with_public_api(app_settings=AppSettings(ENVIRONMENT="production"))


@pytest.mark.asyncio
async def test_public_docs_are_always_reachable(it_combined_app: FastAPI) -> None:
    async with (
        asgi_lifespan.LifespanManager(it_combined_app, startup_timeout=_STARTUP_TIMEOUT_S),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_combined_app),
            base_url="http://test",
        ) as client,
    ):
        docs_response = await client.get("/public/docs")
        redoc_response = await client.get("/public/redoc")

    assert docs_response.status_code == 200
    assert redoc_response.status_code == 200


@pytest.mark.asyncio
async def test_private_docs_stay_gated_in_production(it_combined_app: FastAPI) -> None:
    # Proves make_app() itself is untouched by this feature -- its own
    # ENVIRONMENT-gated /docs still 404s in production, on the SAME
    # combined app that just proved /public/docs is always-on.
    async with (
        asgi_lifespan.LifespanManager(it_combined_app, startup_timeout=_STARTUP_TIMEOUT_S),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_combined_app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/docs")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mounted_sub_app_actually_answers_requests(it_combined_app: FastAPI) -> None:
    # /public/openapi.json always exists (FastAPI auto-generates it) and
    # its content is specific to the public app's own title -- an
    # unambiguous proof that requests under /public/... really reach the
    # MOUNTED sub-app's own container/routing, not just a prefix match on
    # the outer app that silently fails to route anywhere. No leaf
    # business route exists yet at this step (Steps 7+ add those), so
    # this is the strongest available proof rather than the
    # "GET /public/v1/api-keys/ -> 401" check the plan originally
    # sketched before that route existed -- see the plan's own Step 6
    # note on this.
    async with (
        asgi_lifespan.LifespanManager(it_combined_app, startup_timeout=_STARTUP_TIMEOUT_S),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_combined_app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/public/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Public API"


@pytest.mark.asyncio
async def test_authenticated_routes_document_api_key_header(it_combined_app: FastAPI) -> None:
    """
    ApiKeyIdentityProvider reads X-API-Key straight off the raw Starlette
    Request (see its own docstring), never through a FastAPI-visible
    Depends()/Security() parameter -- FastAPI's OpenAPI generation only
    knows about parameters it can see on the route function's own
    signature, so without a documentation-only Depends(APIKeyHeader(...))
    on each route, Swagger renders no way to authorize the call at all
    (confirmed manually: "Try it out" on /public/v1/api-keys/ shows
    nothing to put the key in, so a caller sends no header and gets a
    genuine, but confusing, 401). This mirrors the private app's own
    account/profile.py, which already documents its cookie the same way
    via APIKeyCookie. This test catches any authenticated public-API
    route that forgets to add the equivalent APIKeyHeader declaration.

    OpenAPI 3 represents an API-key credential via
    components.securitySchemes (type: apiKey) plus a per-operation
    `security` list referencing it by scheme name -- NOT as a `parameters`
    entry (that's only for plain Header()/Query()/Path() function args).
    Swagger's per-route padlock and "Authorize" dialog read from exactly
    that security/securitySchemes pairing, so that's what this test has to
    check instead.
    """
    async with (
        asgi_lifespan.LifespanManager(it_combined_app, startup_timeout=_STARTUP_TIMEOUT_S),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_combined_app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/public/openapi.json")

    schema = response.json()
    api_key_header_scheme_names = {
        name
        for name, scheme in schema["components"]["securitySchemes"].items()
        if scheme.get("type") == "apiKey" and scheme.get("in") == "header" and scheme.get("name") == API_KEY_HEADER_NAME
    }
    assert api_key_header_scheme_names, "No security scheme documents the X-API-Key header at all"

    for method, path in _API_KEY_AUTHENTICATED_ROUTES:
        operation_security = schema["paths"][path][method].get("security", [])
        referenced_scheme_names = {name for requirement in operation_security for name in requirement}
        assert referenced_scheme_names & api_key_header_scheme_names, (
            f"{method.upper()} {path} does not require the {API_KEY_HEADER_NAME} security scheme"
        )


@pytest.mark.asyncio
async def test_combined_lifespan_starts_and_stops_cleanly_twice(it_combined_app: FastAPI) -> None:
    # Starlette's Mount does not forward the ASGI lifespan protocol to a
    # mounted sub-application on its own -- make_app_with_public_api() has
    # to compose both lifespans explicitly (see its own docstring).
    # Running startup/shutdown twice on the SAME app instance proves that
    # composition doesn't leak state or double-invoke either container's
    # teardown (e.g. closing the public container's AsyncEngine twice).
    for _ in range(2):
        async with asgi_lifespan.LifespanManager(it_combined_app, startup_timeout=_STARTUP_TIMEOUT_S):
            pass
