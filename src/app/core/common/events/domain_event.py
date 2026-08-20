import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Any, Self, get_type_hints
from uuid import UUID

# Maps a Python type to a function that turns a value of that type into
# something JSON can represent (e.g. a datetime becomes a plain string).
# Used by to_payload() when building a message body for a task queue.
_ENCODERS: dict[type, Callable[[Any], Any]] = {
    datetime: lambda v: v.isoformat(),
    UUID: str,
}
# The inverse of _ENCODERS: turns the JSON-safe representation back into
# the real Python value. Used by from_payload() to rebuild an event.
_DECODERS: dict[type, Callable[[Any], Any]] = {
    datetime: datetime.fromisoformat,
    UUID: UUID,
}


def _unwrap_newtype(tp: Any) -> Any:
    """
    Event fields are often typed with a NewType (e.g. UserId = NewType("UserId", UUID))
    for domain clarity, but _ENCODERS/_DECODERS are keyed by the underlying real type
    (UUID), not the NewType itself. NewType objects store that real type on
    __supertype__, so this unwraps it. Plain types (str, int, ...) don't have
    __supertype__, so they're returned unchanged.
    """
    return getattr(tp, "__supertype__", tp)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """
    Base class for domain events.
    Events are immutable records of something that happened in the domain.
    They carry enough data for handlers to act without querying the database.
    """

    occurred_at: datetime

    def __new__(cls, *_args: Any, **_kwargs: Any) -> Self:
        # DomainEvent itself is abstract -- only concrete subclasses like
        # UserRegisteredEvent should ever be instantiated. This guard raises
        # if someone tries to construct the bare base class directly.
        if cls is DomainEvent:
            raise TypeError("Base DomainEvent cannot be instantiated directly.")
        return object.__new__(cls)

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe dict of this event's fields, for a message queue body."""
        # get_type_hints() resolves the *actual* field types (e.g. "datetime"
        # instead of the string "datetime" that dataclasses.fields() alone
        # would give us, since annotations can be stored as strings).
        hints = get_type_hints(type(self))
        result: dict[str, Any] = {}
        # Walk every dataclass field on this concrete event subclass (e.g.
        # UserRegisteredEvent's user_id/username/email/occurred_at) and
        # encode each value if we know how to make it JSON-safe.
        for field in dataclasses.fields(self):
            base_type = _unwrap_newtype(hints[field.name])
            encode = _ENCODERS.get(base_type)
            value = getattr(self, field.name)
            # Fields with no matching encoder (str, int, bool, ...) are
            # already JSON-safe as-is, so we pass them through unchanged.
            result[field.name] = encode(value) if encode else value
        return result

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        """Inverse of to_payload() -- reconstructs the concrete event subclass."""
        hints = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        # For every field this event class declares, look up the raw value
        # from the payload dict and decode it back into its real Python type
        # (e.g. an ISO string back into a datetime) before reconstructing.
        for field in dataclasses.fields(cls):
            base_type = _unwrap_newtype(hints[field.name])
            decode = _DECODERS.get(base_type)
            raw = payload[field.name]
            kwargs[field.name] = decode(raw) if decode else raw
        # Calling cls(**kwargs) constructs the correct concrete subclass
        # (e.g. UserRegisteredEvent), not the abstract DomainEvent base.
        return cls(**kwargs)
