import logging
from typing import ClassVar, Literal

from app.core.common.events.user_registered import UserRegisteredEvent
from app.core.common.ports.email_sender import EmailSender

logger = logging.getLogger(__name__)

WELCOME_EMAIL_SUBJECT = "Welcome to the platform!"

WELCOME_EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h1 style="color: #2c3e50;">Welcome, {username}!</h1>
  <p>Your account has been successfully created.</p>
  <p>You can now log in and start using the platform.</p>
  <hr style="border: 1px solid #ecf0f1;">
  <p style="color: #95a5a6; font-size: 12px;">
    This is an automated message. Please do not reply.
  </p>
</body>
</html>
"""


class SendWelcomeEmail:
    # A welcome email can safely lag behind the HTTP response -- the new
    # user doesn't need to wait for it before their signup request
    # completes, so this handler runs in the background (via Celery)
    # rather than blocking the request.
    DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "background"

    def __init__(self, email_sender: EmailSender) -> None:
        # email_sender is a port (EmailSender), not a concrete adapter --
        # this handler doesn't know or care whether emails go out via SMTP,
        # a console logger, or anything else.
        self._email_sender = email_sender

    async def handle(self, event: UserRegisteredEvent) -> None:
        logger.info("Sending welcome email to %s", event.email)
        await self._email_sender.send(
            to_email=event.email,
            to_name=event.username,
            subject=WELCOME_EMAIL_SUBJECT,
            html_body=WELCOME_EMAIL_HTML.format(username=event.username),
        )
        logger.info("Welcome email sent to %s", event.email)
