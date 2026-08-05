import logging
from collections.abc import Sequence
from typing import Any

from app.core.common.events.domain_event import DomainEvent
from app.core.common.ports.event_handler import EventHandler

logger = logging.getLogger(__name__)


class SyncEventDispatcher:
    """Dispatches events synchronously. The HTTP response waits for all handlers to complete."""

    def __init__(
        self,
        handler_registry: dict[type[DomainEvent], Sequence[EventHandler[Any]]],
    ) -> None:
        self._handlers = handler_registry

    async def dispatch(self, events: list[DomainEvent]) -> None:
        for event in events:
            handlers = self._handlers.get(type(event), ())
            for handler in handlers:
                logger.info("Dispatching %s to %s", type(event).__name__, type(handler).__name__)
                await handler.handle(event)
