import logging
from typing import ClassVar, Literal

from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent
from app.core.common.ports.email_sender import EmailSender

logger = logging.getLogger(__name__)

INVITATION_EMAIL_SUBJECT = "You're invited to join {organization_name}"

# No accept link: invitations are accepted only by the logged-in invitee
# (docs/plans/9-organizations.md), so the email just tells them where to look.
# The organization name is safe to drop into HTML as-is: OrganizationName only
# allows letters, digits and separators.
INVITATION_EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h1 style="color: #2c3e50;">You're invited to join {organization_name}</h1>
  <p>{inviter_username} has invited you to join <strong>{organization_name}</strong> as {role}.</p>
  <p>The invitation expires on {expires_on} (UTC).</p>
  <p>Log in and open your pending invitations to accept or decline it.</p>
  <hr style="border: 1px solid #ecf0f1;">
  <p style="color: #95a5a6; font-size: 12px;">
    This is an automated message. Please do not reply.
  </p>
</body>
</html>
"""


class SendOrganizationInvitationEmail:
    # Like SendWelcomeEmail: the inviter's request doesn't wait for the email.
    DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "background"

    def __init__(self, email_sender: EmailSender) -> None:
        self._email_sender = email_sender

    async def handle(self, event: OrganizationInvitationCreatedEvent) -> None:
        logger.info("Sending organization invitation email to %s", event.invitee_email)
        await self._email_sender.send(
            to_emails=[event.invitee_email],
            subject=INVITATION_EMAIL_SUBJECT.format(organization_name=event.organization_name),
            html_body=INVITATION_EMAIL_HTML.format(
                organization_name=event.organization_name,
                inviter_username=event.inviter_username,
                role=event.role,
                expires_on=event.expires_at.strftime("%Y-%m-%d %H:%M"),
            ),
        )
        logger.info("Organization invitation email sent to %s", event.invitee_email)
