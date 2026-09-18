from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from dishka import Provider, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.inbound.http.public_api.router import make_public_router
from app.main.config.loader import load_password_hasher_settings, load_postgres_settings, load_sqla_settings
from app.main.config.settings import PasswordHasherSettings, PostgresSettings, SqlaSettings
from app.main.ioc.public_api import get_public_api_providers
from app.main.run import make_app, make_lifespan


def make_public_api_app(
    *di_providers: Provider,
    password_hasher_settings: PasswordHasherSettings | None = None,
    postgres_settings: PostgresSettings | None = None,
    sqla_settings: SqlaSettings | None = None,
) -> FastAPI:
    """Pass providers to override existing ones for testing."""
    if password_hasher_settings is None:
        password_hasher_settings = load_password_hasher_settings()
    if postgres_settings is None:
        postgres_settings = load_postgres_settings()
    if sqla_settings is None:
        sqla_settings = load_sqla_settings()

    app = FastAPI(
        title="Public API",
        summary="API-key-authenticated surface for programmatic integrations.",
        # Always reachable, unlike the private app's ENVIRONMENT-gated
        # /docs (see make_app() in run.py) -- the point of this feature is
        # that a customer integrating against this API can read its docs
        # regardless of this deployment's ENVIRONMENT.
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=make_lifespan(),  # reused, unmodified, from main/run.py
    )
    container = make_async_container(
        *get_public_api_providers(),
        *di_providers,
        context={
            PasswordHasherSettings: password_hasher_settings,
            PostgresSettings: postgres_settings,
            SqlaSettings: sqla_settings,
        },
    )
    setup_dishka(container, app)
    app.include_router(make_public_router())
    return app


def make_app_with_public_api(*di_providers: Provider, **make_app_kwargs: Any) -> FastAPI:
    """The real process entrypoint (see docker-entrypoint.sh) -- composes
    the existing, unmodified make_app() with the new public sub-app, by
    addition only, never by editing it."""
    app = make_app(*di_providers, **make_app_kwargs)
    public_app = make_public_api_app()
    app.mount("/public", public_app)

    # Starlette's Mount does not forward the ASGI `lifespan` protocol to a
    # mounted sub-application -- it only routes http/websocket scopes by
    # path -- so public_app's own lifespan (and its container's
    # startup/shutdown) would silently never run if left as-is. Compose
    # both lifespans explicitly instead of editing anything in run.py.
    main_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with main_lifespan(app), public_app.router.lifespan_context(public_app):
            yield

    app.router.lifespan_context = combined_lifespan
    return app
