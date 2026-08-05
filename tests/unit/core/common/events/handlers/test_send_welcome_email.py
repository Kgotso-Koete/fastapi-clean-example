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
            to_email="alice@example.com",
            to_name="Alice",
            subject=ANY,
            html_body=ANY,
        )
        # Verify the HTML body contains the username
        call_kwargs = email_sender.send.call_args.kwargs
        assert "Alice" in call_kwargs["html_body"]
