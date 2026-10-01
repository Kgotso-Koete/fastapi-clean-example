from typing import ClassVar

from app.core.common.exceptions import BaseError


class OrganizationNotFoundError(BaseError):
    """
    Raised by CurrentOrganizationService when the caller has no ACCEPTED
    membership in the organization -- a stranger, a still-pending invitee,
    or a member of a different organization. Mapped to HTTP 404, so an
    outsider can't even confirm the organization exists.

    Deliberately NOT a subclass of AuthorizationError (403): that one is
    reserved for a genuine member whose role is too low, and keeping the
    two unrelated means a test expecting one can never be satisfied by the
    other by accident.

    Lives in core.common (next to its only raiser), not core.commands --
    the import contracts forbid core.common from importing core.commands,
    and both commands and queries need to handle it.
    """

    default_message: ClassVar[str] = "Organization not found."
