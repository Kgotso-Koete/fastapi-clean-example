from typing import Any


class SpyEmailSender:
    """Test double that captures sent emails for assertion."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, *, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        self.sent.append(
            {
                "to_email": to_email,
                "to_name": to_name,
                "subject": subject,
                "html_body": html_body,
            }
        )
