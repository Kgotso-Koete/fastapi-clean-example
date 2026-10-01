import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembershipId
from app.core.common.entities.types_ import UserId
from app.core.common.events.handlers.send_organization_invitation_email import (
    SendOrganizationInvitationEmail,
)
from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent

# SendOrganizationInvitationEmail (docs/plans/9-organizations.md, Step 6b):
# tells the invitee who invited them, to which organization, with what role,
# and until when. Mirrors test_send_welcome_email.py.


class TestSendOrganizationInvitationEmail:
    def test_dispatch_mode_is_background(self) -> None:
        # Like the welcome email, it can lag behind the HTTP response: the
        # inviter doesn't wait for the email before their request completes.
        assert SendOrganizationInvitationEmail.DISPATCH_MODE == "background"

    @pytest.mark.asyncio
    async def test_emails_the_invitee_the_invitation_details(self) -> None:
        email_sender = AsyncMock()
        handler = SendOrganizationInvitationEmail(email_sender=email_sender)
        event = OrganizationInvitationCreatedEvent(
            occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            organization_id=OrganizationId(uuid.uuid4()),
            organization_name="Avengers",
            membership_id=OrganizationMembershipId(uuid.uuid4()),
            invitee_user_id=UserId(uuid.uuid4()),
            invitee_email="bruce@example.com",
            inviter_username="tony-stark",
            role="admin",
            expires_at=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        )

        await handler.handle(event)

        # Only the invitee receives it.
        email_sender.send.assert_called_once()
        kwargs = email_sender.send.call_args.kwargs
        assert kwargs["to_emails"] == ["bruce@example.com"]
        assert "Avengers" in kwargs["subject"]
        # Who, where, what role, and until when.
        body = kwargs["html_body"]
        assert "tony-stark" in body
        assert "Avengers" in body
        assert "admin" in body
        assert "2026-06-08" in body
