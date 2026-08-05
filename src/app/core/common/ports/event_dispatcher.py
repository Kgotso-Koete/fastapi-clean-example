from abc import abstractmethod
from typing import Protocol

from app.core.common.events.domain_event import DomainEvent


class EventDispatcher(Protocol):
    """Dispatches domain events to their registered handlers."""

    @abstractmethod
    async def dispatch(self, events: list[DomainEvent]) -> None: ...
