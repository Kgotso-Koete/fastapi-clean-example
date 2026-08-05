import uuid
from datetime import UTC, datetime

import pytest

from app.core.common.entities.types_ import UserId
from app.core.common.events.user_registered import UserRegisteredEvent


class TestUserRegisteredEvent:
    def test_creates_event_with_valid_data(self) -> None:
        user_id = UserId(uuid.uuid4())
        occurred_at = datetime.now(UTC)

        event = UserRegisteredEvent(
            occurred_at=occurred_at,
            user_id=user_id,
            username="testuser",
            email="test@example.com",
        )

        assert event.occurred_at == occurred_at
        assert event.user_id == user_id
        assert event.username == "testuser"
        assert event.email == "test@example.com"

    def test_event_is_immutable(self) -> None:
        event = UserRegisteredEvent(
            occurred_at=datetime.now(UTC),
            user_id=UserId(uuid.uuid4()),
            username="testuser",
            email="test@example.com",
        )

        with pytest.raises(AttributeError):
            event.username = "changed"  # type: ignore[misc]
