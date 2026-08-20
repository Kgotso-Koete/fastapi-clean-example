from abc import abstractmethod
from typing import ClassVar, Literal, Protocol

from app.core.common.events.domain_event import DomainEvent


class EventHandler[T: DomainEvent](Protocol):
    """
    Handles a specific type of domain event.

    DISPATCH_MODE controls how HybridEventDispatcher runs *this* handler:
      - "sync": awaited inline, blocking the caller until it completes.
        Use when the caller needs the result before responding (e.g. the
        user must see confirmation before the response returns).
      - "background": handed off to Celery (see app.main.worker). Use when
        the handler can lag behind the response without the caller caring.

    Every concrete handler MUST declare this next to handle() -- there is no
    default value here, so a handler class that forgets it fails Protocol
    conformance (caught by mypy) the moment it's placed into a handler
    registry.
    """

    DISPATCH_MODE: ClassVar[Literal["sync", "background"]]

    @abstractmethod
    async def handle(self, event: T) -> None: ...
