import logging

from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.common.ports.email_sender import EmailSender
from app.inbound.http.auth_cookie_middleware import AuthCookieMiddleware
from app.inbound.http.errors.alerting import AlertCooldown, build_error_alert_email
from app.inbound.http.errors.internal_server_error import internal_server_error
from app.main.config.logging_ import DATEFMT, FMT, HumanReadableFormatter, JsonFormatter, LoggingLevel
from app.main.config.settings import AlertSettings, CookieSettings

logger = logging.getLogger(__name__)

# Counts every exception that reaches the global catch-all handler below —
# i.e. genuine server-side failures, never the mapped business exceptions
# that already resolve to their own 4xx responses via fastapi-error-map.
# Scrape via /metrics; graph/alert on it in Prometheus/Grafana as
# `rate(app_unhandled_exceptions_total[5m])` by `exception_type`.
UNHANDLED_EXCEPTIONS_TOTAL = Counter(
    "app_unhandled_exceptions_total",
    "Total unhandled exceptions that reached the global exception handler.",
    ["exception_type"],
)


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

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        exception_type = type(exc).__name__
        logger.exception(
            "Unhandled exception",
            extra={
                "exception_type": exception_type,
                "path": request.url.path,
                "method": request.method,
            },
        )
        UNHANDLED_EXCEPTIONS_TOTAL.labels(exception_type=exception_type).inc()

        if alert_settings.ENABLED and alert_cooldown.should_send(exception_type):
            await _try_send_alert_email(request, exc, alert_settings)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=internal_server_error(exc),
        )

    logger.info("Global exception handlers are set up")


async def _try_send_alert_email(request: Request, exc: Exception, alert_settings: AlertSettings) -> None:
    """Best-effort: a broken alert channel must never break error handling itself."""
    try:
        email_sender = await request.state.dishka_container.get(EmailSender)
        subject, html_body = build_error_alert_email(exc, request)
        await email_sender.send(
            to_email=alert_settings.TO_EMAIL,
            to_name=alert_settings.TO_NAME,
            subject=subject,
            html_body=html_body,
        )
    except Exception:
        logger.exception("Failed to send critical-error alert email")
