from datetime import datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID

from app.core.common.entities.base import Entity
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.common.organization_exceptions import InvalidMembershipExpiryError
from app.core.common.value_objects.utc_datetime import UtcDatetime

OrganizationMembershipId = NewType("OrganizationMembershipId", UUID)


class OrganizationRole(StrEnum):
    """
    What an account can do INSIDE one specific organization. Deliberately
    independent of UserRole (types_.py), which governs what an account can
    do to the platform itself -- the two role lists never reference each
    other.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationMembership(Entity[OrganizationMembershipId]):
    """
    The join between one User and one Organization, with that user's role
    inside it. A pending invite and an active membership are the SAME row,
    distinguished only by accepted_at being None or set -- the same
    nullable set-once timestamp shape as ApiKey.revoked_at.
    """

    def __init__(
        self,
        *,
        id_: OrganizationMembershipId,
        organization_id: OrganizationId,
        user_id: UserId,
        role: OrganizationRole,
        invited_by_user_id: UserId,
        created_at: UtcDatetime,
        accepted_at: UtcDatetime | None = None,
        # Deliberately NO default: every caller must state the expiry
        # explicitly, so forgetting it can't silently create an invitation
        # that never expires. See the invariant check just below.
        expires_at: UtcDatetime | None,
    ) -> None:
        # Exactly one of accepted_at/expires_at is set: a pending invitation
        # always expires, an accepted membership never does. The TTL itself
        # comes from settings (ORGANIZATION_INVITATION_TTL_DAYS), applied by
        # InviteOrganizationMember -- not hardcoded here.
        if (accepted_at is None) == (expires_at is None):
            raise InvalidMembershipExpiryError
        super().__init__(id_=id_)
        self.organization_id = organization_id
        self.user_id = user_id
        self.role = role
        self.invited_by_user_id = invited_by_user_id
        self._created_at = created_at
        # Goes through the property setter below, NOT a SQLAlchemy
        # composite() -- see the accepted_at docstring for why.
        self.accepted_at = accepted_at
        # Same nullable-property shape as accepted_at. Set on a pending
        # invitation (InviteOrganizationMember, Step 6); None on the
        # creator's own OWNER row, and cleared by accept().
        self.expires_at = expires_at

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at

    @property
    def accepted_at(self) -> UtcDatetime | None:
        """
        Backed by _accepted_at, a plain nullable `datetime` column -- not a
        composite(UtcDatetime, ...). Same reasoning as ApiKey.revoked_at:
        composite() crashes on a NULL column when loading, and its
        None-tolerant workaround breaks writing instead. Doing the
        None-check here in plain Python sidesteps both halves of that bug.
        See docs/plans/8-public-api-key-auth.md's Step 3 notes.
        """
        return UtcDatetime(self._accepted_at) if self._accepted_at is not None else None

    @accepted_at.setter
    def accepted_at(self, value: UtcDatetime | None) -> None:
        self._accepted_at: datetime | None = value.value if value is not None else None

    @property
    def is_accepted(self) -> bool:
        return self._accepted_at is not None

    @property
    def expires_at(self) -> UtcDatetime | None:
        """Same reasoning as accepted_at's property above -- backed by the
        plain nullable _expires_at column, not a composite()."""
        return UtcDatetime(self._expires_at) if self._expires_at is not None else None

    @expires_at.setter
    def expires_at(self, value: UtcDatetime | None) -> None:
        self._expires_at: datetime | None = value.value if value is not None else None

    def is_expired(self, now: UtcDatetime) -> bool:
        # The same `now >= expires_at` boundary as ApiKey.is_expired(), so
        # "expired" means one thing everywhere. No expires_at means the row
        # can never expire (an owner row, or an already-accepted member).
        return self._expires_at is not None and now.value >= self._expires_at

    def renew_invitation(
        self,
        *,
        role: OrganizationRole,
        invited_by_user_id: UserId,
        now: UtcDatetime,
        expires_at: UtcDatetime,
    ) -> None:
        # Re-inviting over an EXPIRED pending invitation reuses this same row:
        # the unique (organization_id, user_id) constraint rules out a second
        # one. Everything about the invitation starts over -- who sent it,
        # which role it grants, when it was sent, when it lapses. Whether the
        # row is eligible for renewal (pending AND expired) is the calling
        # command's decision, like accept()'s idempotency.
        self.role = role
        self.invited_by_user_id = invited_by_user_id
        self._created_at = now
        self.expires_at = expires_at

    def accept(self, *, now: UtcDatetime) -> None:
        # Deliberately just sets the timestamp. Whether a repeat accept is a
        # no-op is the AcceptOrganizationInvitation command's decision
        # (Step 6), mirroring how RevokeApiKey -- not ApiKey.revoke() --
        # owns revoke's idempotency. Rejecting an EXPIRED invitation is
        # likewise the command's job (InvitationExpiredError); the entity
        # only guarantees an accepted membership never expires afterwards.
        self.accepted_at = now
        self.expires_at = None
