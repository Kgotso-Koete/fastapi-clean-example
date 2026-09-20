from typing import Any, cast

import pytest
from dishka import AsyncContainer
from fastapi import FastAPI
from starlette.requests import Request

from app.core.commands.issue_api_key import IssueApiKey
from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.ports.access_revoker import AccessRevoker
from app.core.common.ports.identity_provider import IdentityProvider
from app.core.queries.ports.api_key_reader import ApiKeyReader
from app.main.run_public_api import make_public_api_app

# No interactors exist yet at this step (see the plan's own Step 5 note) --
# this only proves ApiKeyProvider's infra-only bindings resolve cleanly
# inside a real container, against real Postgres.


def _make_request() -> Request:
    # A minimal, real starlette Request -- resolving IdentityProvider here
    # constructs a real ApiKeyIdentityProvider, which needs a Request in
    # its REQUEST scope (via RequestProvider's from_context()), even
    # though this test never calls get_current_user_id() on it.
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": [],
    }
    return Request(scope)


@pytest.fixture
def it_public_app() -> FastAPI:
    return make_public_api_app()


@pytest.fixture
def it_public_container(it_public_app: FastAPI) -> AsyncContainer:
    # Starlette's app.state attributes are typed Any -- cast to the real
    # type dishka's own setup_dishka() actually stores there.
    return cast(AsyncContainer, it_public_app.state.dishka_container)


@pytest.mark.parametrize(
    "port",
    [CurrentUserService, ApiKeyRepository, ApiKeyReader, IdentityProvider, AccessRevoker, IssueApiKey],
)
@pytest.mark.asyncio
async def test_resolves_every_infra_binding_without_error(
    it_public_container: AsyncContainer,
    port: type,
) -> None:
    async with it_public_container(context={Request: _make_request()}) as request_container:
        resolved: object = await request_container.get(port)

    assert resolved is not None
