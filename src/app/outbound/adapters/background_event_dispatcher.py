import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from app.core.common.events.domain_event import DomainEvent
from app.core.common.ports.event_handler import EventHandler

logger = logging.getLogger(__name__)


class BackgroundEventDispatcher:
    """
    Dispatches events as background async tasks via asyncio.create_task().
    Framework-independent — works with any async Python framework.
    The HTTP response returns immediately without waiting for handlers.
    """

    def __init__(
        self,
        handler_registry: dict[type[DomainEvent], Sequence[EventHandler[Any]]],
    ) -> None:
        self._handlers = handler_registry
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def dispatch(self, events: list[DomainEvent]) -> None:
        for event in events:
            handlers = self._handlers.get(type(event), ())
            for handler in handlers:
                logger.info(
                    "Scheduling background dispatch: %s -> %s",
                    type(event).__name__,
                    type(handler).__name__,
                )
                task = asyncio.create_task(
                    self._safe_handle(handler, event),
                    name=f"{type(event).__name__}->{type(handler).__name__}",
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

    @staticmethod
    async def _safe_handle(handler: EventHandler[Any], event: DomainEvent) -> None:
        """Wraps handler execution with error logging so background failures don't crash."""
        try:
            await handler.handle(event)
        except Exception:
            logger.exception(
                "Background event handler failed: %s handling %s",
                type(handler).__name__,
                type(event).__name__,
            )
