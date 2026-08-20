from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NewType
from uuid import UUID, uuid4

import pytest

from app.core.common.events.domain_event import DomainEvent

# A throwaway NewType, mirroring how real events type identifiers (e.g.
# UserId = NewType("UserId", UUID)). Used to test that to_payload()/
# from_payload() correctly unwrap NewType down to the real UUID type.
_StubId = NewType("_StubId", UUID)


@dataclass(frozen=True, slots=True, kw_only=True)
class _StubEvent(DomainEvent):
    """Concrete subclass used only in these tests."""

    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _StubEventWithId(DomainEvent):
    """Concrete subclass with a NewType-over-UUID field, used only in these tests."""

    stub_id: _StubId


class TestDomainEventCannotBeInstantiatedDirectly:
    def test_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="Base DomainEvent cannot be instantiated directly"):
            DomainEvent(occurred_at=datetime.now(UTC))


class TestDomainEventSubclass:
    def test_can_be_created(self) -> None:
        now = datetime.now(UTC)

        event = _StubEvent(occurred_at=now, detail="test")

        assert event.occurred_at == now
        assert event.detail == "test"

    def test_is_immutable(self) -> None:
        event = _StubEvent(occurred_at=datetime.now(UTC), detail="test")

        with pytest.raises(AttributeError):
            event.detail = "changed"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        now = datetime.now(UTC)

        e1 = _StubEvent(occurred_at=now, detail="test")
        e2 = _StubEvent(occurred_at=now, detail="test")

        assert e1 == e2

    def test_inequality_by_value(self) -> None:
        now = datetime.now(UTC)

        e1 = _StubEvent(occurred_at=now, detail="a")
        e2 = _StubEvent(occurred_at=now, detail="b")

        assert e1 != e2


class TestDomainEventPayloadRoundTrip:
    """
    to_payload()/from_payload() let an event cross a process boundary (e.g. to a
    Celery task) as a plain JSON-safe dict. These tests check both directions.
    """

    def test_to_payload_encodes_datetime_as_isoformat_string(self) -> None:
        # datetime isn't valid JSON on its own -- to_payload() must convert it
        # to an ISO-8601 string so it can safely go into a message body.
        now = datetime.now(UTC)
        event = _StubEvent(occurred_at=now, detail="test")

        payload = event.to_payload()

        assert payload == {"occurred_at": now.isoformat(), "detail": "test"}

    def test_to_payload_encodes_newtype_over_uuid_as_string(self) -> None:
        # A field typed as a NewType-over-UUID (like real event ID fields)
        # should still be encoded as a plain string, same as a bare UUID.
        now = datetime.now(UTC)
        stub_id = _StubId(uuid4())
        event = _StubEventWithId(occurred_at=now, stub_id=stub_id)

        payload = event.to_payload()

        assert payload == {"occurred_at": now.isoformat(), "stub_id": str(stub_id)}

    def test_from_payload_is_the_inverse_of_to_payload(self) -> None:
        # Encoding an event and then decoding it back should reproduce an
        # equal event, with the datetime field restored to a real datetime
        # (not left as the ISO string it was encoded to).
        now = datetime.now(UTC)
        event = _StubEvent(occurred_at=now, detail="test")

        reconstructed = _StubEvent.from_payload(event.to_payload())

        assert reconstructed == event
        assert reconstructed.occurred_at == now
        assert reconstructed.detail == "test"

    def test_from_payload_reconstructs_newtype_over_uuid_field(self) -> None:
        # Same round-trip check, but for the NewType-over-UUID field: the
        # reconstructed value should be a real UUID again, not a string.
        now = datetime.now(UTC)
        stub_id = _StubId(uuid4())
        event = _StubEventWithId(occurred_at=now, stub_id=stub_id)

        reconstructed = _StubEventWithId.from_payload(event.to_payload())

        assert reconstructed == event
        assert reconstructed.stub_id == stub_id
