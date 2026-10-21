from abc import abstractmethod
from typing import ClassVar, Protocol

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.common.exceptions import BaseError


class RowSecurityContextConflictError(BaseError):
    """A request tried to act for a different user or organization than the
    one it already bound. Never expected: it means a bug upstream, so it is
    raised loudly instead of quietly switching (OWASP: the verified context
    must not be replaced downstream)."""

    default_message: ClassVar[str] = "A different user or organization is already bound to this request."


class RowSecurityContext(Protocol):
    """Tells the data store which user and organization the current request
    acts for, so its own isolation rules (Postgres Row-Level Security, plan
    14) apply to every query that follows. Use cases bind only ids they have
    already verified, never a raw value from the request."""

    @abstractmethod
    async def bind_user(self, user_id: UserId) -> None: ...

    @abstractmethod
    async def bind_organization(self, organization_id: OrganizationId) -> None: ...
