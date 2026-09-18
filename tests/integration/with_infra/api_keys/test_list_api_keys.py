from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.api_key import ApiKey
from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.integration.with_infra.factories import create_user_with_password

# No /public prefix -- see conftest.py's own note on this.
API_KEYS_ENDPOINT = "/v1/api-keys/"


async def _issue_key(
    client: httpx2.AsyncClient,
    *,
    username: str,
    password: str,
    label: str | None = None,
) -> dict[str, Any]:
    response = await client.post(
        API_KEYS_ENDPOINT,
        json={"username": username, "password": password, "expires_in_days": 30, "label": label},
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_returns_only_the_authenticated_users_own_keys(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password_a = "correct-password1"
    user_a = await create_user_with_password(it_user_service, raw_password=password_a)
    password_b = "correct-password2"
    user_b = await create_user_with_password(it_user_service, raw_password=password_b)
    it_session.add_all([user_a, user_b])
    await it_session.commit()

    key_a1 = await _issue_key(it_public_client, username=user_a.username.value, password=password_a, label="a1")
    key_a2 = await _issue_key(it_public_client, username=user_a.username.value, password=password_a, label="a2")
    await _issue_key(it_public_client, username=user_b.username.value, password=password_b, label="b1")

    # Revoke one of A's keys directly -- no HTTP revoke endpoint exists yet
    # (that's Step 9); it should still be LISTED, just with revoked_at set.
    revoked_key = await it_session.get(ApiKey, UUID(key_a2["id"]))
    assert revoked_key is not None
    revoked_key.revoke(now=UtcDatetime(datetime.now(UTC)))
    await it_session.commit()

    response = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": key_a1["raw_key"]})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    ids = {k["id"] for k in body["api_keys"]}
    assert ids == {key_a1["id"], key_a2["id"]}
    # Never leaks the other user's key, and never leaks key_hash for any key.
    for entry in body["api_keys"]:
        assert "key_hash" not in entry
    revoked_entry = next(k for k in body["api_keys"] if k["id"] == key_a2["id"])
    assert revoked_entry["revoked_at"] is not None


@pytest.mark.asyncio
async def test_returns_401_for_a_missing_key(it_public_client: httpx2.AsyncClient) -> None:
    response = await it_public_client.get(API_KEYS_ENDPOINT)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_for_an_unknown_key(it_public_client: httpx2.AsyncClient) -> None:
    response = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": "ak_does-not-exist"})

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
    issued = await _issue_key(it_public_client, username=user.username.value, password=password)

    key = await it_session.get(ApiKey, UUID(issued["id"]))
    assert key is not None
    key.revoke(now=UtcDatetime(datetime.now(UTC)))
    await it_session.commit()

    response = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": issued["raw_key"]})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_for_an_expired_key(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    issued = await _issue_key(it_public_client, username=user.username.value, password=password)

    key = await it_session.get(ApiKey, UUID(issued["id"]))
    assert key is not None
    key.expires_at = UtcDatetime(datetime.now(UTC) - timedelta(seconds=1))
    await it_session.commit()

    response = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": issued["raw_key"]})

    assert response.status_code == 401
