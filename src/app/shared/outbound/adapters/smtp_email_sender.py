import logging
from collections.abc import Sequence
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

    async def send(
        self,
        *,
        to_emails: Sequence[str],
        subject: str,
        html_body: str,
        cc_emails: Sequence[str] = (),
        bcc_emails: Sequence[str] = (),
    ) -> None:
        message = MIMEMultipart("alternative")
        message["From"] = f"{self._from_name} <{self._from_email}>"
        message["To"] = ", ".join(to_emails)
        if cc_emails:
            message["Cc"] = ", ".join(cc_emails)
        message["Subject"] = subject
        message.attach(MIMEText(html_body, "html"))

        # bcc_emails are passed only via the SMTP envelope (aiosmtplib's
        # `recipients`), never added as a message header -- a "Bcc" header
        # would defeat the whole point by showing every bcc'd address to
        # every other recipient.
        recipients = [*to_emails, *cc_emails, *bcc_emails]

        logger.info(
            "Sending email via SMTP to=%s cc=%s bcc_count=%d subject=%s host=%s",
            to_emails,
            cc_emails,
            len(bcc_emails),
            subject,
            self._host,
        )

        await aiosmtplib.send(
            message,
            recipients=recipients,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._use_tls if self._port == 465 else False,
            start_tls=self._use_tls if self._port != 465 else False,
        )

        logger.info("Email sent via SMTP to=%s", to_emails)
