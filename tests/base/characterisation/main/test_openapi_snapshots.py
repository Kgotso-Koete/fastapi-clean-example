"""
Characterisation tests for both OpenAPI documents (docs/plans/16-modular-monolith.md,
Step 0). They record what the two apps serve today, so a restructuring step that
changes any route, schema, description or their order fails here, even when no
behaviour test notices. They are not a RED/GREEN cycle: they pin existing
behaviour and pass once the snapshots are written (O2: strict).

To write or deliberately refresh the snapshots, run from the repository root:

    uv run python -m tests.base.characterisation.main.test_openapi_snapshots

then review the diff of tests/base/characterisation/main/openapi_snapshots/ before committing it.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Final

import httpx2
import pytest
from fastapi import FastAPI

from app.base.main.config.settings import (
    AlertSettings,
    ApiKeySettings,
    AppSettings,
    CelerySettings,
    CookieSettings,
    JwtSettings,
    PasswordHasherSettings,
    PostgresSettings,
    RedisSettings,
    SessionSettings,
    SqlaSettings,
)
from app.base.main.run import make_app
from app.base.main.run_public_api import make_public_api_app
from app.modules.organizations.main.config.settings import OrganizationSettings
from app.shared.main.config.settings import EmailSettings

SNAPSHOT_DIR: Final[Path] = Path(__file__).parent / "openapi_snapshots"

# The URL each document is served at, keyed by the name its snapshot file uses
# (the same names as generated_openapi_documents in tests/base/sanity/inbound/http/conftest.py).
DOCUMENT_URLS: Final[dict[str, str]] = {
    "cookie_app": "/openapi.json",
    "public_api_app": "/public/openapi.json",
}

# Every settings class is passed in literally, so a developer's .env (for example
# APP_VERSION, which becomes the document's version) can't make the snapshot
# differ between machines. Only the values that have no default are filled in;
# no connection is opened, because serving /openapi.json never touches the container.
_POSTGRES = PostgresSettings(DB="db", HOST="host", PORT=5432, USER="user", PASSWORD="password")
_PASSWORD_HASHER = PasswordHasherSettings(PEPPER="p" * 32)
_SQLA = SqlaSettings()


def _make_served_app() -> FastAPI:
    # Mirrors make_app_with_public_api() in src/app/base/main/run_public_api.py, the
    # real process entrypoint: the cookie app with the public API mounted at
    # /public. That function isn't called directly because it loads the public
    # app's settings from the environment, which the literal settings above avoid.
    app = make_app(
        app_settings=AppSettings(),
        postgres_settings=_POSTGRES,
        sqla_settings=_SQLA,
        password_hasher_settings=_PASSWORD_HASHER,
        jwt_settings=JwtSettings(SECRET="s" * 32),
        session_settings=SessionSettings(),
        cookie_settings=CookieSettings(),
        email_settings=EmailSettings(),
        redis_settings=RedisSettings(),
        celery_settings=CelerySettings(),
        alert_settings=AlertSettings(),
        organization_settings=OrganizationSettings(),
    )
    public_app = make_public_api_app(
        password_hasher_settings=_PASSWORD_HASHER,
        postgres_settings=_POSTGRES,
        sqla_settings=_SQLA,
        api_key_settings=ApiKeySettings(),
    )
    app.mount("/public", public_app)
    return app


def _render(document: object) -> str:
    # Pretty-printed so a failing comparison shows a readable diff. Key order is
    # kept as served (no sort_keys), because the order is what Swagger shows.
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


async def fetch_openapi_documents() -> dict[str, str]:
    # make_app() calls setup_logging(), which replaces the root logger's
    # handlers and level for the whole process. Restoring them afterwards keeps
    # this test from changing how every later test in the session logs.
    root_logger = logging.getLogger()
    saved_handlers, saved_level = root_logger.handlers[:], root_logger.level
    try:
        app = _make_served_app()
    finally:
        root_logger.handlers[:] = saved_handlers
        root_logger.setLevel(saved_level)

    # Fetched over HTTP, as a client would, rather than by calling app.openapi():
    # FastAPI adds the mounted app's "servers" entry (/public) only while
    # serving a request, so only the served document shows it.
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        documents: dict[str, str] = {}
        for name, url in DOCUMENT_URLS.items():
            response = await client.get(url)
            response.raise_for_status()
            documents[name] = _render(response.json())
    return documents


def write_openapi_snapshots() -> None:
    """Writes today's documents as the snapshots (see the module docstring)."""
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    for name, text in asyncio.run(fetch_openapi_documents()).items():
        (SNAPSHOT_DIR / f"{name}.json").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("name", list(DOCUMENT_URLS))
async def test_the_served_openapi_document_matches_its_committed_snapshot(name: str) -> None:
    snapshot = SNAPSHOT_DIR / f"{name}.json"
    assert snapshot.exists(), (
        f"No snapshot at {snapshot}. Write it with: "
        "uv run python -m tests.base.characterisation.main.test_openapi_snapshots"
    )

    served = (await fetch_openapi_documents())[name]

    assert served == snapshot.read_text(encoding="utf-8")


if __name__ == "__main__":
    # Run as a module (see the module docstring) to write the snapshots; pytest
    # only imports this file, so it never runs this block.
    write_openapi_snapshots()
