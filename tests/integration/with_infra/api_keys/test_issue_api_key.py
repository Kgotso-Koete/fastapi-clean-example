from uuid import UUID

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.services.user import UserService
from app.outbound.persistence_sqla.mappings.api_key import api_keys_table
from tests.integration.with_infra.factories import create_user_with_password

# No /public prefix -- it_public_client talks directly to the standalone
# public app (make_public_api_app()), unmounted. The /public prefix only
# exists once make_app_with_public_api() mounts this same app onto the
# combined one (see test_public_docs_availability.py's own note on this).
ISSUE_API_KEY_ENDPOINT = "/v1/api-keys/"


@pytest.mark.asyncio
async def test_returns_201_with_a_raw_key_that_is_never_the_stored_hash(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    raw_password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=raw_password)
    it_session.add(user)
    await it_session.commit()

    response = await it_public_client.post(
        ISSUE_API_KEY_ENDPOINT,
        json={"username": user.username.value, "password": raw_password, "expires_in_days": 30},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["raw_key"].startswith("ak_")

    # The persisted row's key_hash must never equal, or even contain, the
    # raw key -- this is the concrete "only the hash is ever stored" proof
    # the plan's whole hashing decision hinges on.
    result = await it_session.execute(select(api_keys_table.c.key_hash).where(api_keys_table.c.id == UUID(body["id"])))
    stored_hash = result.scalar_one()
    assert stored_hash != body["raw_key"]
    assert body["raw_key"] not in stored_hash


@pytest.mark.asyncio
async def test_returns_401_for_unknown_username(it_public_client: httpx2.AsyncClient) -> None:
    response = await it_public_client.post(
        ISSUE_API_KEY_ENDPOINT,
        json={"username": "does-not-exist", "password": "irrelevant-password1", "expires_in_days": 30},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_for_wrong_password(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    user = await create_user_with_password(it_user_service, raw_password="correct-password1")
    it_session.add(user)
    await it_session.commit()

    response = await it_public_client.post(
        ISSUE_API_KEY_ENDPOINT,
        json={"username": user.username.value, "password": "definitely-the-wrong-one1", "expires_in_days": 30},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_for_an_inactive_account(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    raw_password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=raw_password, is_active=False)
    it_session.add(user)
    await it_session.commit()

    response = await it_public_client.post(
        ISSUE_API_KEY_ENDPOINT,
        json={"username": user.username.value, "password": raw_password, "expires_in_days": 30},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_returns_400_for_out_of_range_expiry(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_public_client: httpx2.AsyncClient,
) -> None:
    raw_password = "correct-password1"
    user = await create_user_with_password(it_user_service, raw_password=raw_password)
    it_session.add(user)
    await it_session.commit()

    response = await it_public_client.post(
        ISSUE_API_KEY_ENDPOINT,
        json={"username": user.username.value, "password": raw_password, "expires_in_days": 9999},
    )

    assert response.status_code == 400
