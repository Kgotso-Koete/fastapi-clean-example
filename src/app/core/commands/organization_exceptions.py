from typing import ClassVar

from app.core.common.exceptions import BaseError

# Errors raised by the organization commands (docs/plans/9-organizations.md).
# Kept in their own file, like api_key_exceptions.py, rather than added to
# the original author's core/commands/exceptions.py. Each error is added in
# the TDD cycle whose use case first raises it.


class UnknownInviteeError(BaseError):
    """Raised by InviteOrganizationMember when no ACTIVE account has the
    given username (HTTP 404). An inactive account gets the same error as a
    missing one, so an invitation can't be used to probe account state."""

    default_message: ClassVar[str] = "No active user with that username."


class CannotGrantOwnerRoleError(BaseError):
    """Raised when someone who is not an OWNER tries to grant the OWNER role
    (HTTP 403). Only an existing OWNER may create another -- the same rule as
    apptension/saas-boilerplate's CreateTenantInvitationSerializer."""

    default_message: ClassVar[str] = "Only an owner can grant the owner role."


class MembershipAlreadyExistsError(BaseError):
    """Raised by InviteOrganizationMember when the invitee is already a member,
    or already has a pending invitation that hasn't expired (HTTP 409). Checked
    before insert, so the unique (organization_id, user_id) constraint never
    surfaces as a raw database IntegrityError."""

    default_message: ClassVar[str] = "This user is already a member or has a pending invitation."


class MembershipNotFoundError(BaseError):
    """Raised when a membership or invitation doesn't exist in the given
    organization, OR exists but isn't the caller's to act on (HTTP 404). The
    two cases are deliberately indistinguishable, so a user can't confirm that
    someone else's invitation exists by probing membership ids."""

    default_message: ClassVar[str] = "Membership not found."


class InvitationExpiredError(BaseError):
    """Raised by AcceptOrganizationInvitation for a pending invitation past its
    expires_at (HTTP 410 Gone -- it existed, but can no longer be used). The
    row is left in place, so an ADMIN can re-invite and renew it."""

    default_message: ClassVar[str] = "This invitation has expired."


class CannotManageOwnerError(BaseError):
    """Raised when someone who is not an OWNER tries to remove an OWNER, or
    change an OWNER's role (HTTP 403). An ADMIN may manage admins and members,
    never an owner -- apptension/saas-boilerplate's rule."""

    default_message: ClassVar[str] = "Only an owner can remove or change another owner."


class LastOwnerError(BaseError):
    """Raised when removing, demoting, or letting leave the organization's last
    ACCEPTED owner (HTTP 409). An organization must always keep an owner;
    promoting someone else to OWNER first is the way out."""

    default_message: ClassVar[str] = "The organization's last owner cannot be removed or demoted."
