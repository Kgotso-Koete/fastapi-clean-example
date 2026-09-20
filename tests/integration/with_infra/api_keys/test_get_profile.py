from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.api_key import ApiKey
from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.integration.with_infra.account.constants import PROFILE_ENDPOINT as PRIVATE_PROFILE_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_user_with_password

# No /public prefix -- see conftest.py's own note on this.
API_KEYS_ENDPOINT = "/v1/api-keys/"
PROFILE_ENDPOINT = "/v1/account/profile/"


async def _issue_key(
    client: httpx2.AsyncClient,
    *,
    identifier: str,
    password: str,
) -> dict[str, Any]:
    response = await client.post(
        API_KEYS_ENDPOINT,
        json={"identifier": identifier, "password": password, "expires_in_days": 30, "label": None},
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_returns_200_identical_to_the_private_apps_profile_for_the_same_account(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_client: httpx2.AsyncClient,
    it_public_client: httpx2.AsyncClient,
) -> None:
    # The concrete "same thing works either way" proof: one account, two
    # entirely different auth mechanisms, same underlying GetOwnProfile.
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()

    await authenticate(it_client, user.username.value, password)
    private_response = await it_client.get(PRIVATE_PROFILE_ENDPOINT)
    assert private_response.status_code == 200

    key = await _issue_key(it_public_client, identifier=user.username.value, password=password)
    public_response = await it_public_client.get(PROFILE_ENDPOINT, headers={"X-API-Key": key["raw_key"]})

    assert public_response.status_code == 200
    assert public_response.json() == private_response.json()


@pytest.mark.asyncio
async def test_returns_401_for_a_missing_key(it_public_client: httpx2.AsyncClient) -> None:
    response = await it_public_client.get(PROFILE_ENDPOINT)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_for_an_unknown_key(it_public_client: httpx2.AsyncClient) -> None:
    response = await it_public_client.get(PROFILE_ENDPOINT, headers={"X-API-Key": "ak_does-not-exist"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_for_a_revoked_key(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    issued = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    key = await it_session.get(ApiKey, UUID(issued["id"]))
    assert key is not None
    key.revoke(now=UtcDatetime(datetime.now(UTC)))
    await it_session.commit()

    response = await it_public_client.get(PROFILE_ENDPOINT, headers={"X-API-Key": issued["raw_key"]})

    assert response.status_code == 401
