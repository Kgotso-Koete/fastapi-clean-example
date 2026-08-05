import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


class SmtpEmailSender:
    """
    Sends emails via SMTP. Truly vendor-independent — works with any SMTP provider.
    Switch providers by changing host/port/credentials in env vars. Zero code changes.
    Uses Python's built-in email.mime for message building (no extra dependencies).
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name
        self._use_tls = use_tls

    async def send(self, *, to_email: str, to_name: str, subject: str, html_body: str) -> None:
        message = MIMEMultipart("alternative")
        message["From"] = f"{self._from_name} <{self._from_email}>"
        message["To"] = f"{to_name} <{to_email}>"
        message["Subject"] = subject
        message.attach(MIMEText(html_body, "html"))

        logger.info("Sending email via SMTP to=%s subject=%s host=%s", to_email, subject, self._host)

        await aiosmtplib.send(
            message,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._use_tls if self._port == 465 else False,
            start_tls=self._use_tls if self._port != 465 else False,
        )

        logger.info("Email sent via SMTP to=%s", to_email)
