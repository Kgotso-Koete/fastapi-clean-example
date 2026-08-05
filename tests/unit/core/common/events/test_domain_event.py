from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.core.common.events.domain_event import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class _StubEvent(DomainEvent):
    """Concrete subclass used only in these tests."""

    detail: str


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
