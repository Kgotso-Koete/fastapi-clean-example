import logging

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.inbound.http.auth_cookie_middleware import AuthCookieMiddleware
from app.inbound.http.errors.alerting import AlertCooldown
from app.inbound.http.errors.exception_middleware import GlobalExceptionMiddleware
from app.main.config.logging_ import DATEFMT, FMT, HumanReadableFormatter, JsonFormatter, LoggingLevel
from app.main.config.settings import AlertSettings, CookieSettings

logger = logging.getLogger(__name__)


def setup_logging(*, level: LoggingLevel = LoggingLevel.INFO, log_format: str = "human") -> None:
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(HumanReadableFormatter(fmt=FMT, datefmt=DATEFMT))

    logging.basicConfig(
        level=level,
        handlers=[handler],
        force=True,
    )
    logger.info("Logging is set up")


def setup_middlewares(app: FastAPI, cookie_settings: CookieSettings) -> None:
    app.add_middleware(
        AuthCookieMiddleware,
        cookie_name=cookie_settings.NAME,
        cookie_path=cookie_settings.PATH,
        cookie_httponly=cookie_settings.HTTPONLY,
        cookie_secure=cookie_settings.SECURE,
        cookie_samesite=cookie_settings.SAMESITE,
    )
    logger.info("Middlewares are set up")


def setup_metrics(app: FastAPI, *, service_name: str) -> None:
    """
    Exposes GET /metrics in Prometheus text format: request counts, latency
    histograms, and in-progress requests, labeled by method/handler/status.
    Scrape it with a local Prometheus (see docker-compose.yml) and graph it
    in Grafana — both ship in this repo's docker-compose for local use.
    """
    Instrumentator().instrument(app, metric_namespace=service_name.replace("-", "_")).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )
    logger.info("Metrics are set up, exposed at /metrics")


def setup_global_exception_handlers(app: FastAPI, *, alert_settings: AlertSettings) -> None:
    alert_cooldown = AlertCooldown(cooldown_s=alert_settings.COOLDOWN_S)
    app.add_middleware(
        GlobalExceptionMiddleware,
        alert_enabled=alert_settings.ENABLED,
        alert_to_email=alert_settings.TO_EMAIL,
        alert_to_name=alert_settings.TO_NAME,
        alert_cooldown=alert_cooldown,
    )
    logger.info("Global exception handlers are set up")
