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


@pytest.mark.asyncio
async def test_returns_204_and_revokes_the_key(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    issued = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    response = await it_public_client.delete(
        f"{API_KEYS_ENDPOINT}{issued['id']}/",
        headers={"X-API-Key": issued["raw_key"]},
    )

    assert response.status_code == 204
    # The just-revoked key must now fail authentication on any endpoint --
    # using it here for the follow-up GET is the simplest proof of that.
    follow_up = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": issued["raw_key"]})
    assert follow_up.status_code == 401


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

    # B tries to revoke A's key using B's own (valid) credentials.
    response = await it_public_client.delete(
        f"{API_KEYS_ENDPOINT}{key_a['id']}/",
        headers={"X-API-Key": key_b["raw_key"]},
    )

    assert response.status_code == 403
    # A's key must still work -- the forbidden attempt must not have
    # revoked it as a side effect.
    still_works = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": key_a["raw_key"]})
    assert still_works.status_code == 200


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
    issued = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    response = await it_public_client.delete(
        f"{API_KEYS_ENDPOINT}{uuid4()}/",
        headers={"X-API-Key": issued["raw_key"]},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_repeated_revoke_is_idempotent(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    # Issue a SECOND key to authenticate with -- the first key gets
    # revoked partway through, so it can no longer authenticate the
    # second (repeated) revoke call.
    issued = await _issue_key(it_public_client, identifier=user.username.value, password=password)
    auth_key = await _issue_key(it_public_client, identifier=user.username.value, password=password)

    first = await it_public_client.delete(
        f"{API_KEYS_ENDPOINT}{issued['id']}/",
        headers={"X-API-Key": auth_key["raw_key"]},
    )
    second = await it_public_client.delete(
        f"{API_KEYS_ENDPOINT}{issued['id']}/",
        headers={"X-API-Key": auth_key["raw_key"]},
    )

    assert first.status_code == 204
    assert second.status_code == 204
