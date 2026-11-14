from abc import abstractmethod
from typing import Any, Protocol


class OutboxRepository(Protocol):
    """Transactional: commit required."""

    @abstractmethod
    def add(self, *, event_type: str, handler_type: str, payload: dict[str, Any]) -> None: ...
