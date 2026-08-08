import html
import time
from collections.abc import Callable
from dataclasses import dataclass, field

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


def build_error_alert_email(exc: Exception, request: Request) -> tuple[str, str]:
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
    )
    return subject, html_body
