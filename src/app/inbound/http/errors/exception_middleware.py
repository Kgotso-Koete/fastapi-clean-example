import logging
from collections.abc import Sequence

from prometheus_client import Counter
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.ports.email_sender import EmailSender
from app.inbound.http.errors.alerting import AlertCooldown, RequestUserContext, build_error_alert_email
from app.inbound.http.errors.internal_server_error import internal_server_error
from app.outbound.auth_ctx.exceptions import AuthenticationError

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


class GlobalExceptionMiddleware:
    """Pure ASGI middleware that catches unhandled exceptions.

    Replaces ``@app.exception_handler(Exception)`` to avoid the duplicate
    traceback problem.  When ``AuthCookieMiddleware`` (a ``BaseHTTPMiddleware``
    subclass) sits above Starlette's router-level ``ExceptionMiddleware``,
    ``call_next`` re-raises the original exception even after
    ``ExceptionMiddleware`` has already handled it, which then reaches
    ``ServerErrorMiddleware`` and uvicorn, producing a second traceback.

    As a pure ASGI middleware registered *above* ``AuthCookieMiddleware`` in
    the stack, this catches the exception before it can propagate further.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        alert_enabled: bool,
        alert_to_emails: Sequence[str],
        alert_cooldown: AlertCooldown,
        alert_cc_emails: Sequence[str] = (),
        alert_bcc_emails: Sequence[str] = (),
    ) -> None:
        self.app = app
        self._alert_enabled = alert_enabled
        self._alert_to_emails = alert_to_emails
        self._alert_cc_emails = alert_cc_emails
        self._alert_bcc_emails = alert_bcc_emails
        self._alert_cooldown = alert_cooldown

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            request = Request(scope)
            await self._handle(request, exc)
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=internal_server_error(exc),
            )
            await response(scope, receive, send)

    async def _handle(self, request: Request, exc: Exception) -> None:
        exception_type = type(exc).__name__
        user_context = await _try_get_request_user_context(request)
        logger.exception(
            "Unhandled exception",
            extra={
                "exception_type": exception_type,
                "path": request.url.path,
                "method": request.method,
                **user_context.as_log_fields(),
            },
        )
        UNHANDLED_EXCEPTIONS_TOTAL.labels(exception_type=exception_type).inc()

        if self._alert_enabled and self._alert_cooldown.should_send(exception_type):
            await _try_send_alert_email(
                request,
                exc,
                to_emails=self._alert_to_emails,
                cc_emails=self._alert_cc_emails,
                bcc_emails=self._alert_bcc_emails,
                user_context=user_context,
            )


async def _try_get_request_user_context(request: Request) -> RequestUserContext:
    """
    Best-effort: resolving identity must never crash error handling itself.
    If the original failure already broke the request's DB session, or the
    DB itself is down, this degrades to "unknown" rather than blocking the
    500 response or masking the real error with a new one.
    """
    try:
        current_user_service = await request.state.dishka_container.get(CurrentUserService)
        user = await current_user_service.get_current_user()
    except (AuthenticationError, AuthorizationError):
        # AuthenticationError: no session at all (no cookie, unknown session, expired).
        # AuthorizationError: session was valid, but the user behind it has since
        # been deleted/deactivated. Both mean "no usable identity for this request".
        return RequestUserContext(status="anonymous")
    except Exception:
        logger.debug("Could not resolve current user for error context", exc_info=True)
        return RequestUserContext(status="unknown")

    return RequestUserContext(
        status="authenticated",
        user_id=str(user.id_),
        username=user.username.value,
        email=user.email.value,
        phone_number=user.phone_number.value,
    )


async def _try_send_alert_email(
    request: Request,
    exc: Exception,
    *,
    to_emails: Sequence[str],
    cc_emails: Sequence[str],
    bcc_emails: Sequence[str],
    user_context: RequestUserContext,
) -> None:
    """Best-effort: a broken alert channel must never break error handling itself."""
    try:
        email_sender = await request.state.dishka_container.get(EmailSender)
        subject, html_body = build_error_alert_email(exc, request, user_context)
        await email_sender.send(
            to_emails=to_emails,
            subject=subject,
            html_body=html_body,
            cc_emails=cc_emails,
            bcc_emails=bcc_emails,
        )
    except Exception:
        logger.exception("Failed to send critical-error alert email")
