import logging
from typing import Any

import pytest
from dishka import make_async_container
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main.config.settings import PostgresSettings, SqlaSettings
from app.main.ioc import outbound
from app.main.ioc.outbound import PersistenceSqlaProvider


class _FakeEngine:
    """Stands in for the real AsyncEngine, so no database is needed. The
    provider disposes the engine when the container closes, so it needs an
    awaitable dispose()."""

    async def dispose(self) -> None:
        return None


async def test_engine_uses_the_configured_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # SQLA_CONNECT_TIMEOUT_S must actually reach the database driver
    # (docs/plans/15-upstream-autumn-2026.md, Step 4), not just load. Instead
    # of timing a real failed connection (slow, and flaky on a busy machine),
    # create_async_engine is swapped for a recorder, and the test checks the
    # connect_args the provider handed it. 7 is deliberately not the default 5,
    # so a hard-coded 5 fails this test.
    received: dict[str, Any] = {}

    def _record_engine_args(**kwargs: Any) -> _FakeEngine:
        received.update(kwargs)
        return _FakeEngine()

    monkeypatch.setattr(outbound, "create_async_engine", _record_engine_args)
    postgres = PostgresSettings(DB="db", HOST="host", PORT=5432, USER="user", PASSWORD="password")
    container = make_async_container(
        PersistenceSqlaProvider(),
        context={PostgresSettings: postgres, SqlaSettings: SqlaSettings(CONNECT_TIMEOUT_S=7)},
    )

    await container.get(AsyncEngine)
    await container.close()

    assert received["connect_args"] == {"connect_timeout": 7}


async def test_engine_creation_never_logs_the_database_password(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The provider logs a DEBUG line when it builds the engine. It used to
    # print the whole connection string, password included, so anyone running
    # with APP_LOGGING_LEVEL=DEBUG wrote the Postgres password into the logs
    # (docs/plans/15-upstream-autumn-2026.md, Step 4b; OWASP's Logging Cheat
    # Sheet: never log passwords or connection strings). The line must still
    # say which database it connected to, so it stays useful when debugging.
    monkeypatch.setattr(outbound, "create_async_engine", lambda **_: _FakeEngine())
    caplog.set_level(logging.DEBUG, logger=outbound.__name__)
    postgres = PostgresSettings(DB="appdb", HOST="db.internal", PORT=6543, USER="appuser", PASSWORD="s3cret-db-pw")
    container = make_async_container(
        PersistenceSqlaProvider(),
        context={PostgresSettings: postgres, SqlaSettings: SqlaSettings()},
    )

    await container.get(AsyncEngine)
    await container.close()

    assert "s3cret-db-pw" not in caplog.text
    assert "db.internal:6543/appdb" in caplog.text
