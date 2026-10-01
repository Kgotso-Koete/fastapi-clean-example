from typing import ClassVar

from app.core.common.exceptions import BaseError


class InvalidMembershipExpiryError(BaseError):
    """
    Raised by OrganizationMembership's constructor when accepted_at and
    expires_at are not exactly one-set, one-None: a pending invitation must
    always expire, and an accepted membership never does.

    A programming error, not bad user input -- no caller-supplied value can
    produce it, so it deliberately has no HTTP error mapping (unlike
    BusinessTypeError's 400). Lives in core.common, not
    core/commands/organization_exceptions.py, because the entity that
    raises it lives in core.common, which must never import commands.
    """

    default_message: ClassVar[str] = "A pending invitation must have an expiry, and an accepted membership must not."
