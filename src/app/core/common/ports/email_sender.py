from abc import abstractmethod
from typing import Protocol


class EmailSender(Protocol):
    """Port for sending emails. Implementations may use SMTP, console logging, etc."""

    @abstractmethod
    async def send(
        self,
        *,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
    ) -> None: ...
