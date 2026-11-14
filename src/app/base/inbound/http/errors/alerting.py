import html
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from starlette.requests import Request


@dataclass
class AlertCooldown:
    """
    Tracks, per exception type, whether enough time has passed to send
    another alert email.

    Keeps a single noisy failure (e.g. a DB outage throwing the same
    exception on every request) from flooding an inbox, while still
    re-alerting if the same problem is still happening minutes later.
    Different exception types are rate-limited independently, so one
    exception type spiking doesn't silence alerts for an unrelated one.
    """

    cooldown_s: float
    clock: Callable[[], float] = field(default=time.monotonic)
    _last_sent_at: dict[str, float] = field(default_factory=dict, init=False)

    def should_send(self, exception_type: str) -> bool:
        now = self.clock()
        last_sent = self._last_sent_at.get(exception_type)
        if last_sent is not None and (now - last_sent) < self.cooldown_s:
            return False
        self._last_sent_at[exception_type] = now
        return True


@dataclass(frozen=True)
class RequestUserContext:
    """
    What we know about who made the request that hit an unhandled error.

    Deliberately three states, not just "user or None": "anonymous" (no valid
    session - expected, not a problem) and "unknown" (we tried to resolve the
    session and couldn't - e.g. the DB is down, which for a 500 investigation
    is itself useful information) are different facts and shouldn't collapse
    into the same "no user" bucket.

    Only ever built from a request that already hit the global error handler,
    so the PII fields (email, phone_number) are populated for error diagnosis
    only - never attached to routine, non-error request logs.
    """

    status: Literal["authenticated", "anonymous", "unknown"]
    user_id: str | None = None
    username: str | None = None
    email: str | None = None
    phone_number: str | None = None

    def as_log_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {"user_status": self.status}
        if self.user_id is not None:
            fields["user_id"] = self.user_id
        if self.username is not None:
            fields["username"] = self.username
        if self.email is not None:
            fields["user_email"] = self.email
        if self.phone_number is not None:
            fields["user_phone_number"] = self.phone_number
        return fields


def build_error_alert_email(exc: Exception, request: Request, user_context: RequestUserContext) -> tuple[str, str]:
    """Builds a (subject, html_body) pair for a critical-error alert email.

    Only called for exceptions that reach the global catch-all handler —
    i.e. genuine unhandled/server errors, never the business-rule exceptions
    that already have their own mapped 4xx responses (see fastapi-error-map
    rules), so this never fires for ordinary user-input mistakes.
    """
    exception_type = type(exc).__name__
    path = f"{request.method} {request.url.path}"
    client_host = request.client.host if request.client else "unknown"

    subject = f"[ALERT] {exception_type} on {path}"
    html_body = (
        "<h2>Unhandled server error</h2>"
        f"<p><b>Type:</b> {html.escape(exception_type)}</p>"
        f"<p><b>Message:</b> {html.escape(str(exc))}</p>"
        f"<p><b>Request:</b> {html.escape(path)}</p>"
        f"<p><b>Client:</b> {html.escape(client_host)}</p>"
        f"<p><b>User:</b> {html.escape(_describe_user(user_context))}</p>"
    )
    return subject, html_body


def _describe_user(user_context: RequestUserContext) -> str:
    if user_context.status == "authenticated":
        return (
            f"{user_context.username} "
            f"(id={user_context.user_id}, email={user_context.email}, phone={user_context.phone_number})"
        )
    if user_context.status == "anonymous":
        return "anonymous (no valid session)"
    return "unknown (couldn't resolve session - see logs)"
