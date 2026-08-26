import uuid
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock

import pytest

from app.core.common.entities.types_ import UserId
from app.core.common.events.handlers.send_welcome_email import (
    SendWelcomeEmail,
)
from app.core.common.events.user_registered import UserRegisteredEvent


class TestSendWelcomeEmail:
    def test_dispatch_mode_is_background(self) -> None:
        # SendWelcomeEmail can safely lag behind the HTTP response -- the
        # user doesn't need to wait for the email to send before their
        # signup request completes. HybridEventDispatcher reads this
        # class attribute to decide whether to await this handler inline
        # or hand it off to Celery.
        assert SendWelcomeEmail.DISPATCH_MODE == "background"

    @pytest.mark.asyncio
    async def test_handles_event_and_sends_email(self) -> None:
        email_sender = AsyncMock()
        handler = SendWelcomeEmail(email_sender=email_sender)

        event = UserRegisteredEvent(
            occurred_at=datetime.now(UTC),
            user_id=UserId(uuid.uuid4()),
            username="Alice",
            email="alice@example.com",
        )

        await handler.handle(event)

        email_sender.send.assert_called_once_with(
            to_emails=["alice@example.com"],
            subject=ANY,
            html_body=ANY,
        )
        # Verify the HTML body contains the username
        call_kwargs = email_sender.send.call_args.kwargs
        assert "Alice" in call_kwargs["html_body"]
