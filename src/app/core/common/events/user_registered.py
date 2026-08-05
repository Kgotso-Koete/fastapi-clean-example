from dataclasses import dataclass

from app.core.common.entities.types_ import UserId
from app.core.common.events.domain_event import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRegisteredEvent(DomainEvent):
    """Raised when a new user account is created (via signup or admin creation)."""

    user_id: UserId
    username: str
    email: str
