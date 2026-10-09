import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.services.user import UserService
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.username import Username
from app.outbound.auth_ctx.model import AuthSession
from tests.integration.with_infra.account.constants import AUTH_COOKIE_NAME, LOG_IN_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import (
    create_raw_password,
    create_raw_username,
    create_user_with_password,
)


async def _count_auth_sessions(session: AsyncSession) -> int:
    # How many login sessions the auth_sessions table holds. Each test starts
    # with an empty database (it_db_clean). Logging in must create exactly one
    # row, and a refused login none, so a refusal can't leave a usable session
    # behind (the original author's tests; docs/plans/15-upstream-autumn-2026.md,
    # Step 5). int(... or 0), as SqlaUserReader does: SQLAlchemy types a bare
    # COUNT as Any.
    return int(await session.scalar(select(func.count()).select_from(AuthSession)) or 0)


async def test_returns_200_and_sets_cookie(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    payload = {"identifier": user.username.value, "password": password}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 200
    assert AUTH_COOKIE_NAME in r.cookies

    data = r.json()
    assert data["username"] == user.username.value
    assert data["role"] == user.role.value
    assert data["is_active"] is True
    assert "id" in data
    assert "password_hash" not in data
    auth_session = (await it_session.execute(select(AuthSession))).scalar_one()
    assert auth_session.user_id == user.id_


async def test_returns_200_and_sets_cookie_when_logging_in_with_email(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    payload = {"identifier": user.email.value, "password": password}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 200
    assert AUTH_COOKIE_NAME in r.cookies

    data = r.json()
    assert data["username"] == user.username.value


async def test_returns_400_when_username_is_too_short(
    it_client: httpx2.AsyncClient,
) -> None:
    payload = {"identifier": "x" * (Username.MIN_LEN - 1), "password": create_raw_password()}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 400


async def test_returns_400_when_password_is_too_short(
    it_client: httpx2.AsyncClient,
) -> None:
    payload = {"identifier": create_raw_username(), "password": "x" * (RawPassword.MIN_LEN - 1)}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 400


async def test_returns_401_when_user_does_not_exist(
    it_client: httpx2.AsyncClient,
) -> None:
    payload = {"identifier": create_raw_username(), "password": create_raw_password()}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 401


async def test_returns_401_when_password_is_wrong(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user = await create_user_with_password(it_user_service)
    it_session.add(user)
    await it_session.commit()
    payload = {"identifier": user.username.value, "password": create_raw_password()}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 401
    assert await _count_auth_sessions(it_session) == 0


async def test_returns_401_when_user_is_inactive(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password, is_active=False)
    it_session.add(user)
    await it_session.commit()
    payload = {"identifier": user.username.value, "password": password}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 401
    assert await _count_auth_sessions(it_session) == 0


async def test_returns_403_when_already_authenticated(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    payload = {"identifier": user.username.value, "password": password}

    r = await it_client.post(LOG_IN_ENDPOINT, json=payload)

    assert r.status_code == 403
    # Still only the first login's session: a second login while logged in
    # adds none.
    assert await _count_auth_sessions(it_session) == 1
