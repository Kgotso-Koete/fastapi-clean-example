from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """
    Base class for domain events.
    Events are immutable records of something that happened in the domain.
    They carry enough data for handlers to act without querying the database.
    """

    occurred_at: datetime

    def __new__(cls, *_args: Any, **_kwargs: Any) -> Self:
        if cls is DomainEvent:
            raise TypeError("Base DomainEvent cannot be instantiated directly.")
        return object.__new__(cls)
