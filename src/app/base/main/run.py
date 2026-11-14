from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from dishka import Provider, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.base.inbound.http.root_router import make_fastapi_root_router
from app.base.main.config.loader import (
    load_alert_settings,
    load_app_settings,
    load_celery_settings,
    load_cookie_settings,
    load_email_settings,
    load_jwt_settings,
    load_organization_settings,
    load_password_hasher_settings,
    load_postgres_settings,
    load_redis_settings,
    load_session_settings,
    load_sqla_settings,
)
from app.base.main.config.settings import (
    AlertSettings,
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
from app.base.main.ioc.provider_registry import get_providers
from app.base.main.modules import UNITS, TableMapping, Unit, collect_routers, collect_table_mappings
from app.base.main.setup import setup_global_exception_handlers, setup_logging, setup_metrics, setup_middlewares
from app.base.outbound.persistence_sqla.mappings.all import map_tables
from app.modules.organizations.main.config.settings import OrganizationSettings
from app.shared.main.config.settings import EmailSettings


def make_lifespan(*, table_mappings: Sequence[TableMapping]) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Here one can bind APP-scoped dependencies to `app.state` and close them if needed"""
        # https://dishka.readthedocs.io/en/stable/integrations/fastapi.html
        container = app.state.dishka_container
        try:
            # Base's tables, then the registered units' (plan 16, Step 4d).
            map_tables(module_mappings=table_mappings)
            yield
        finally:
            await container.close()

    return lifespan


def make_app(  # noqa: C901 -- new alert_settings branch pushed this past the complexity limit;
    # left as-is rather than refactoring existing code without being asked (see PR discussion)
    *di_providers: Provider,
    # The registered units to build the app with (docs/plans/16-modular-monolith.md,
    # "The registry"). Production takes the default, every unit in UNITS; the
    # feature-delete test passes fewer to prove the app runs without a module.
    units: Sequence[Unit] = UNITS,
    app_settings: AppSettings | None = None,
    postgres_settings: PostgresSettings | None = None,
    sqla_settings: SqlaSettings | None = None,
    password_hasher_settings: PasswordHasherSettings | None = None,
    jwt_settings: JwtSettings | None = None,
    session_settings: SessionSettings | None = None,
    cookie_settings: CookieSettings | None = None,
    email_settings: EmailSettings | None = None,
    redis_settings: RedisSettings | None = None,
    celery_settings: CelerySettings | None = None,
    alert_settings: AlertSettings | None = None,
    organization_settings: OrganizationSettings | None = None,
) -> FastAPI:
    """Pass providers to override existing ones for testing."""
    if app_settings is None:
        app_settings = load_app_settings()

    setup_logging(level=app_settings.LOGGING_LEVEL, log_format=app_settings.LOG_FORMAT)

    if postgres_settings is None:
        postgres_settings = load_postgres_settings()
    if sqla_settings is None:
        sqla_settings = load_sqla_settings()
    if password_hasher_settings is None:
        password_hasher_settings = load_password_hasher_settings()
    if jwt_settings is None:
        jwt_settings = load_jwt_settings()
    if session_settings is None:
        session_settings = load_session_settings()
    if cookie_settings is None:
        cookie_settings = load_cookie_settings()
    if email_settings is None:
        email_settings = load_email_settings()
    if redis_settings is None:
        redis_settings = load_redis_settings()
    if celery_settings is None:
        celery_settings = load_celery_settings()
    if alert_settings is None:
        alert_settings = load_alert_settings()
    # Organizations (docs/plans/9-organizations.md): the invitation TTL.
    if organization_settings is None:
        organization_settings = load_organization_settings()

    # /openapi.json stays reachable regardless (e.g. to import the schema
    # into Postman/Insomnia) -- only the interactive HTML pages are dev-only.
    docs_reachable = app_settings.ENVIRONMENT == "development"
    app = FastAPI(
        debug=app_settings.DEBUG_MODE,
        title=app_settings.SERVICE_NAME,
        version=app_settings.VERSION,
        summary=f"OpenAPI schema for {app_settings.SERVICE_NAME}",
        lifespan=make_lifespan(table_mappings=collect_table_mappings(unit.TABLE_MAPPINGS for unit in units)),
        root_path=app_settings.ROOT_PATH.rstrip("/"),
        docs_url="/docs" if docs_reachable else None,
        redoc_url="/redoc" if docs_reachable else None,
    )
    container = make_async_container(
        *get_providers(units),
        *di_providers,
        context={
            AppSettings: app_settings,
            PostgresSettings: postgres_settings,
            SqlaSettings: sqla_settings,
            PasswordHasherSettings: password_hasher_settings,
            JwtSettings: jwt_settings,
            SessionSettings: session_settings,
            CookieSettings: cookie_settings,
            EmailSettings: email_settings,
            RedisSettings: redis_settings,
            CelerySettings: celery_settings,
            AlertSettings: alert_settings,
            OrganizationSettings: organization_settings,
        },
    )
    setup_dishka(container, app)
    setup_middlewares(app, cookie_settings)
    setup_metrics(app, service_name=app_settings.SERVICE_NAME)
    setup_global_exception_handlers(app, alert_settings=alert_settings)
    app.include_router(
        make_fastapi_root_router(
            debug_mode=app_settings.DEBUG_MODE,
            cookie_name=cookie_settings.NAME,
            # Each registered unit's private routers (plan 16, "The registry"),
            # so an app built without a unit serves none of its routes.
            module_routers=collect_routers(unit.make_web_routers(cookie_name=cookie_settings.NAME) for unit in units),
        )
    )
    return app


if __name__ == "__main__":
    """See clck.ru/3RUG2j if debug in PyCharm is broken"""
    import uvicorn

    uvicorn.run(app=make_app())
