from copy import deepcopy
from typing import Any

import pytest
from fastapi import FastAPI

from app.inbound.http.public_api.router import make_public_router
from app.inbound.http.root_router import make_fastapi_root_router
from app.main.config.settings import CookieSettings


@pytest.fixture(scope="session")
def generated_openapi_documents() -> dict[str, dict[str, Any]]:
    # The OpenAPI document (what /docs renders) of each app this codebase
    # serves, built from its routers alone: no database, settings files or
    # DI container needed. Upstream has only the cookie app; this codebase
    # also serves the public API-key app (mounted at /public), which has
    # request bodies of its own, so both are checked
    # (docs/plans/15-upstream-autumn-2026.md, Step 5, item 10).
    cookie_app = FastAPI()
    cookie_app.include_router(make_fastapi_root_router(debug_mode=False, cookie_name=CookieSettings().NAME))
    public_api_app = FastAPI()
    public_api_app.include_router(make_public_router())
    return {"cookie_app": cookie_app.openapi(), "public_api_app": public_api_app.openapi()}


@pytest.fixture(params=["cookie_app", "public_api_app"])
def openapi_document(
    request: pytest.FixtureRequest,
    generated_openapi_documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # Every test that asks for openapi_document runs once per app (the
    # [cookie_app] and [public_api_app] suffixes in pytest's output). A deep
    # copy, as upstream does, so no test can change the document another sees.
    return deepcopy(generated_openapi_documents[request.param])
