from collections.abc import AsyncIterator
from typing import Final

import asgi_lifespan
import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.main.config.loader import load_postgres_runtime_role_settings, load_postgres_settings
from app.main.config.settings import AppSettings, CelerySettings, PostgresSettings
from app.main.run import make_app

# The same startup budget it_client gives the owner app.
_LIFESPAN_STARTUP_TIMEOUT_S: Final = 30


def _runtime_role_postgres_settings() -> PostgresSettings:
    # The owner's host, port and database with only the login changed to the
    # runtime role (app_user), as in test_runtime_role.py.
    owner_settings = load_postgres_settings()
    runtime_role_settings = load_postgres_runtime_role_settings()
    return owner_settings.model_copy(
        update={"USER": runtime_role_settings.USER, "PASSWORD": runtime_role_settings.PASSWORD},
    )


@pytest.fixture
async def owner_connection() -> AsyncIterator[AsyncConnection]:
    """A connection logged in as the table owner (postgres), rolled back afterwards.

    The owner can read the whole catalog and change grants and RLS flags.
    Postgres can undo GRANT, REVOKE and ALTER TABLE inside a transaction, so
    a test may set up exactly the state it needs and leave nothing behind:
    the rollback below discards it. Its own short-lived engine, disposed at
    the end, so no connection lingers between tests.
    """
    engine = create_async_engine(load_postgres_settings().dsn)
    try:
        async with engine.connect() as connection:
            yield connection
            await connection.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def runtime_connection() -> AsyncIterator[AsyncConnection]:
    """A connection logged in as the runtime role (app_user), the role the web app will use.

    OWASP: test isolation "through the same role, connection path, and pooling
    mode used by the application", so the matrix tests never read through
    the owner, who bypasses every policy. Same host, port and database as
    the owner's settings; only the login changes (as in test_runtime_role.py).
    It sees only committed rows, so tests seed through it_session, which
    commits, and it_db_clean truncates before the next test.
    """
    engine = create_async_engine(_runtime_role_postgres_settings().dsn)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


@pytest.fixture
def runtime_fastapi_app() -> FastAPI:
    """The web app with its database engine logged in as app_user, the role it
    will run as in production (plan 14, "Order of work").

    Only the requests under test go through it. Setup stays on the owner app
    (it_client, it_session, it_user_service), because app_user may not
    TRUNCATE and RLS would filter the seeding. Celery is off, so no broker is
    needed; no route tested here stages a background event yet.
    """
    return make_app(
        app_settings=AppSettings(DEBUG_MODE=False),
        celery_settings=CelerySettings(ENABLED=False),
        postgres_settings=_runtime_role_postgres_settings(),
    )


@pytest.fixture
async def runtime_client(runtime_fastapi_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    # Same shape as it_client, for the app running as app_user.
    async with (
        asgi_lifespan.LifespanManager(runtime_fastapi_app, startup_timeout=_LIFESPAN_STARTUP_TIMEOUT_S),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=runtime_fastapi_app), base_url="http://test") as client,
    ):
        yield client
