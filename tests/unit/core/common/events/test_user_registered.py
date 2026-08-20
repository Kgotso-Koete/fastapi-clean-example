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


class TestUserRegisteredEventPayloadRoundTrip:
    """
    Checks the real event (not just the DomainEvent base tested elsewhere)
    actually round-trips through to_payload()/from_payload() -- this is the
    exact payload shape a Celery task receives and must reconstruct.
    """

    def test_to_payload_from_payload_round_trip(self) -> None:
        user_id = UserId(uuid.uuid4())
        occurred_at = datetime.now(UTC)
        event = UserRegisteredEvent(
            occurred_at=occurred_at,
            user_id=user_id,
            username="testuser",
            email="test@example.com",
        )

        # Encode to a JSON-safe dict...
        payload = event.to_payload()
        # ...and decode it straight back into a UserRegisteredEvent.
        reconstructed = UserRegisteredEvent.from_payload(payload)

        # occurred_at and user_id are converted to plain strings in the
        # payload; username/email are already strings, so they pass through.
        assert payload == {
            "occurred_at": occurred_at.isoformat(),
            "user_id": str(user_id),
            "username": "testuser",
            "email": "test@example.com",
        }
        # The reconstructed event should be equal to the original, with
        # user_id restored as a real UserId (UUID), not the string it was
        # encoded to.
        assert reconstructed == event
        assert reconstructed.user_id == user_id
