from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserQm:
    id: UUID
    username: str
    email: str
    phone_number: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # None when the user has none (docs/plans/10-profile-editing.md,
    # decision 4). Deliberately no default: every UserQm(...) must say what
    # the description is, so mypy catches one that forgets it (a default let
    # LogIn silently answer null).
    description: str | None
