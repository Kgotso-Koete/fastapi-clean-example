import httpx2
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.auth_ctx.model import AuthSession
from tests.integration.with_infra.account.constants import AUTH_COOKIE_NAME, LOG_OUT_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_raw_now, create_raw_password, create_user_with_password


async def _count_auth_sessions(session: AsyncSession) -> int:
    # How many login sessions the auth_sessions table holds. Each test starts
    # with an empty database (it_db_clean), so after one login this is 1.
    # int(... or 0), as SqlaUserReader does: SQLAlchemy types a bare COUNT as Any.
    return int(await session.scalar(select(func.count()).select_from(AuthSession)) or 0)


async def test_returns_204_and_clears_cookie(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    # Proves this test's own database session sees the row the app committed
    # in its session at login, so the 0 below means "deleted", not "never seen"
    # (docs/plans/15-upstream-autumn-2026.md, Step 5).
    assert await _count_auth_sessions(it_session) == 1

    r = await it_client.delete(LOG_OUT_ENDPOINT)

    assert r.status_code == 204
    assert AUTH_COOKIE_NAME not in it_client.cookies
    # Logging out ends the session on the server, not only in the browser: a
    # copied cookie can't be replayed once its row is gone (the original
    # author's test_returns_204_and_ends_session).
    assert await _count_auth_sessions(it_session) == 0


async def test_returns_401_when_not_authenticated(
    it_client: httpx2.AsyncClient,
) -> None:
    r = await it_client.delete(LOG_OUT_ENDPOINT)

    assert r.status_code == 401


async def test_returns_401_when_session_is_terminated(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The cookie is still valid and signed, but its session row was deleted
    # on the server (as logging out elsewhere or deactivation does). The
    # cookie alone must not be enough (the original author's test).
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    await it_session.execute(delete(AuthSession))
    await it_session.commit()

    r = await it_client.delete(LOG_OUT_ENDPOINT)

    assert r.status_code == 401


async def test_returns_401_when_session_is_expired(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The session row still exists, but its expiry has passed: the server's
    # expiry, not the cookie's, decides (the original author's test).
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    auth_session = (await it_session.execute(select(AuthSession))).scalar_one()
    auth_session.expiration = UtcDatetime(create_raw_now())
    await it_session.commit()

    r = await it_client.delete(LOG_OUT_ENDPOINT)

    assert r.status_code == 401


async def test_returns_403_and_revokes_sessions_when_user_is_inactive(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A user deactivated while logged in: their next request is refused, and
    # every session they hold is deleted, so no other cookie of theirs works
    # either (CurrentUserService's inactive-user guard; the original author's
    # test). The API-key side of this is tested in
    # api_keys/test_inactive_user_revokes_keys.py.
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    assert await _count_auth_sessions(it_session) == 1
    it_user_service.set_activation(user, now=UtcDatetime(create_raw_now()), is_active=False)
    await it_session.commit()

    r = await it_client.delete(LOG_OUT_ENDPOINT)

    assert r.status_code == 403
    assert await _count_auth_sessions(it_session) == 0
