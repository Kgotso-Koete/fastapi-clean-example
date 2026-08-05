from datetime import UTC, datetime

from app.core.common.events.domain_event import DomainEvent
from tests.unit.core.common.entities.factories import create_named_entity


class _StubEvent(DomainEvent):
    """Concrete subclass used only in these tests."""


class TestEntityEventRecording:
    def test_new_entity_has_no_events(self) -> None:
        entity = create_named_entity()

        events = entity.collect_events()

        assert events == []

    def test_record_event_adds_to_events_list(self) -> None:
        entity = create_named_entity()
        event = _StubEvent(occurred_at=datetime.now(UTC))

        entity.record_event(event)

        assert entity._events == [event]  # noqa: SLF001

    def test_collect_events_returns_and_clears_events(self) -> None:
        entity = create_named_entity()
        event1 = _StubEvent(occurred_at=datetime.now(UTC))
        event2 = _StubEvent(occurred_at=datetime.now(UTC))
        entity.record_event(event1)
        entity.record_event(event2)

        collected = entity.collect_events()

        assert collected == [event1, event2]
        assert entity.collect_events() == []
        assert entity._events == []  # noqa: SLF001
