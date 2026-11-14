from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol


class EmailSender(Protocol):
    """Port for sending emails. Implementations may use SMTP, console logging, etc."""

    @abstractmethod
    async def send(
        self,
        *,
        to_emails: Sequence[str],
        subject: str,
        html_body: str,
        cc_emails: Sequence[str] = (),
        bcc_emails: Sequence[str] = (),
    ) -> None: ...
