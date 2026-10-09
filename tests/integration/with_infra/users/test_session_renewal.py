from typing import cast

import httpx2
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.user import User
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.main.config.settings import SessionSettings
from app.outbound.auth_ctx.model import AuthSession
from tests.integration.with_infra.account.constants import AUTH_COOKIE_NAME
from tests.integration.with_infra.factories import create_raw_now
from tests.integration.with_infra.users.constants import USERS_ENDPOINT


async def test_returns_200_and_extends_session_when_session_nears_expiration(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_fastapi_app: FastAPI,
    it_admin: User,
) -> None:
    # A session in the last part of its life (the final REFRESH_THRESHOLD_RATIO
    # of its TTL) is renewed by the next request: a fresh cookie, and a later
    # expiry stored on the server, so an active user isn't logged out mid-use
    # (AuthService.get_current_user_id; the original author's test,
    # docs/plans/15-upstream-autumn-2026.md, Step 5). The settings come from
    # the app's own container, so the test follows whatever TTL it runs with.
    container = it_fastapi_app.state.dishka_container
    session_settings = cast(SessionSettings, await container.get(SessionSettings))
    auth_session = (await it_session.execute(select(AuthSession))).scalar_one()
    refresh_window = session_settings.ttl * session_settings.REFRESH_THRESHOLD_RATIO
    near_expiration = UtcDatetime(create_raw_now() + refresh_window / 2)
    auth_session.expiration = near_expiration
    await it_session.commit()

    r = await it_client.get(USERS_ENDPOINT)

    assert r.status_code == 200
    assert AUTH_COOKIE_NAME in r.cookies
    await it_session.refresh(auth_session)
    assert auth_session.expiration > near_expiration
