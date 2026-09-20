from typing import Any
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.services.user import UserService
from tests.integration.with_infra.factories import create_user_with_password

# No /public prefix -- see conftest.py's own note on this.
API_KEYS_ENDPOINT = "/v1/api-keys/"


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


def _usage_url(api_key_id: str) -> str:
    return f"{API_KEYS_ENDPOINT}{api_key_id}/usage/"


@pytest.mark.asyncio
async def test_returns_200_with_use_count_including_the_self_check(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    key = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    # Two authenticated calls with the key itself -- bumps use_count to 2.
    await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": key["raw_key"]})
    await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": key["raw_key"]})

    # Checking the key's OWN usage via itself is also an authenticated
    # request, so it bumps use_count one more time, to 3 -- the
    # self-referential-increment behavior documented in the plan.
    response = await it_public_client.get(_usage_url(key["id"]), headers={"X-API-Key": key["raw_key"]})

    assert response.status_code == 200
    body = response.json()
    assert body["use_count"] == 3
    assert body["last_used_at"] is not None
    assert "user_id" not in body
    assert "key_hash" not in body


@pytest.mark.asyncio
async def test_returns_200_with_zero_use_count_for_a_fresh_unused_key(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    # A SEPARATE key authenticates this check, so the fresh key itself is
    # never used to authenticate anything -- its stats stay genuinely at
    # their issuance defaults, proving this isn't the self-check case.
    auth_key = await _issue_key(it_public_client, identifier=user.username.value, password=password)
    fresh_key = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    response = await it_public_client.get(
        _usage_url(fresh_key["id"]),
        headers={"X-API-Key": auth_key["raw_key"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["use_count"] == 0
    assert body["last_used_at"] is None


@pytest.mark.asyncio
async def test_returns_403_for_another_users_key(
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
    key_a = await _issue_key(it_public_client, identifier=user_a.username.value, password=password_a)
    key_b = await _issue_key(it_public_client, identifier=user_b.username.value, password=password_b)

    response = await it_public_client.get(
        _usage_url(key_a["id"]),
        headers={"X-API-Key": key_b["raw_key"]},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_returns_404_for_an_unknown_id(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    key = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    response = await it_public_client.get(_usage_url(str(uuid4())), headers={"X-API-Key": key["raw_key"]})

    assert response.status_code == 404
