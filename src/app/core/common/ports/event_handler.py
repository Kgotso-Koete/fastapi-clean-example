from abc import abstractmethod
from typing import Protocol

from app.core.common.events.domain_event import DomainEvent


class EventHandler[T: DomainEvent](Protocol):
    """Handles a specific type of domain event."""

    @abstractmethod
    async def handle(self, event: T) -> None: ...
