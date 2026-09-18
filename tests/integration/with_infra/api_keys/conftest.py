from collections.abc import AsyncIterator

import asgi_lifespan
import httpx2
import pytest
from fastapi import FastAPI

from app.main.run_public_api import make_public_api_app

_STARTUP_TIMEOUT_S = 30


@pytest.fixture
def it_public_app() -> FastAPI:
    return make_public_api_app()


@pytest.fixture
async def it_public_client(it_public_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    # Mirrors the top-level conftest's it_client fixture exactly, just
    # against the public app instead of the private one. This app has its
    # own, independent container/connection pool (see the plan's "two
    # connection pools" note) but the same underlying Postgres database,
    # so a User row committed via the private app's it_session (used by
    # tests in this same directory to set up a real account) is visible
    # here too.
    #
    # Important for every endpoint constant a test in this directory
    # defines: this client talks to the STANDALONE public app directly,
    # unmounted -- paths here are just "/v1/...", with NO "/public" prefix.
    # That prefix only exists once make_app_with_public_api() mounts this
    # same app onto the combined one (see test_public_docs_availability.py).
    # A real bug hit once already: an endpoint constant written as
    # "/public/v1/api-keys/" 404'd against this fixture for exactly this
    # reason.
    async with (
        asgi_lifespan.LifespanManager(it_public_app, startup_timeout=_STARTUP_TIMEOUT_S),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_public_app),
            base_url="http://test",
        ) as client,
    ):
        yield client
