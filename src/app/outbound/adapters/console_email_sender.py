import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    """Logs emails to console instead of sending them. For development and testing."""

    async def send(
        self,
        *,
        to_emails: Sequence[str],
        subject: str,
        html_body: str,
        cc_emails: Sequence[str] = (),
        bcc_emails: Sequence[str] = (),
    ) -> None:
        logger.info(
            "EMAIL [to=%s] [cc=%s] [bcc=%s] [subject=%s]\n%s",
            to_emails,
            cc_emails,
            bcc_emails,
            subject,
            html_body,
        )
