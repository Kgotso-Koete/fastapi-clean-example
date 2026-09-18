import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.services.user import UserService
from tests.integration.with_infra.account.constants import PROFILE_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_raw_password, create_user_with_password


async def test_returns_200_with_the_authenticated_users_own_profile(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)

    r = await it_client.get(PROFILE_ENDPOINT)

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(user.id_)
    assert body["username"] == user.username.value
    assert body["email"] == user.email.value
    assert body["phone_number"] == user.phone_number.value
    assert body["role"] == user.role.value
    assert body["is_active"] == user.is_active


async def test_returns_401_when_not_authenticated(
    it_client: httpx2.AsyncClient,
) -> None:
    r = await it_client.get(PROFILE_ENDPOINT)

    assert r.status_code == 401
