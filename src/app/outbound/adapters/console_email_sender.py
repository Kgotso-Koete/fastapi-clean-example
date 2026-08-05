import logging

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    """Logs emails to console instead of sending them. For development and testing."""

    async def send(self, *, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        logger.info(
            "EMAIL [to=%s (%s)] [subject=%s]\n%s",
            to_email,
            to_name,
            subject,
            html_body,
        )
