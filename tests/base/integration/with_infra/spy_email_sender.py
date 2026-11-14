from collections.abc import Sequence
from typing import Any


class SpyEmailSender:
    """Test double that captures sent emails for assertion."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        to_emails: Sequence[str],
        subject: str,
        html_body: str,
        cc_emails: Sequence[str] = (),
        bcc_emails: Sequence[str] = (),
    ) -> None:
        self.sent.append(
            {
                "to_emails": list(to_emails),
                "subject": subject,
                "html_body": html_body,
                "cc_emails": list(cc_emails),
                "bcc_emails": list(bcc_emails),
            }
        )
