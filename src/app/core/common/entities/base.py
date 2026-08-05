from collections.abc import Hashable
from typing import Any, Self, cast

from app.core.common.events.domain_event import DomainEvent


class Entity[T: Hashable]:
    """
    Base class for domain entities, defined by a unique identity (`id`).
    Subclassing is optional; any implementation honoring this contract is valid.
    - `id`: Identity that remains constant throughout the entity's lifecycle.
    - Entities are mutable, but are compared solely by their `id`.
    """

    _events: list[DomainEvent]

    def __new__(cls, *_args: Any, **_kwargs: Any) -> Self:
        if cls is Entity:
            raise TypeError("Base Entity cannot be instantiated directly.")
        return object.__new__(cls)

    def __init__(self, *, id_: T) -> None:
        self.id_ = id_
        object.__setattr__(self, "_events", [])

    def record_event(self, event: DomainEvent) -> None:
        """Record a domain event. Events are collected after the use case commits."""
        self._events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        """Return and clear all recorded events. Call after transaction commit."""
        events = self._events.copy()
        self._events.clear()
        return events

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Prevents modifying the `id` after it's set.
        Other attributes can be changed as usual.
        """
        if name == "id_" and getattr(self, "id_", None) is not None:
            raise AttributeError("Changing entity ID is not permitted.")
        object.__setattr__(self, name, value)

    def __eq__(self, other: object) -> bool:
        """
        Two entities are considered equal if they have the same `id`,
        regardless of other attribute values.
        """
        return type(self) is type(other) and cast(Self, other).id_ == self.id_

    def __hash__(self) -> int:
        """
        Generate a hash based on entity type and the immutable `id`.
        This allows entities to be used in hash-based collections and
        reduces the risk of hash collisions between different entity types.
        """
        return hash((type(self), self.id_))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id_={self.id_!r})"
