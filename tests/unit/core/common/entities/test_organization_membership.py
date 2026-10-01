from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.organization_exceptions import InvalidMembershipExpiryError
from app.core.common.value_objects.utc_datetime import UtcDatetime

_DEFAULT_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_EXPIRES_AT = datetime(2026, 1, 8, tzinfo=UTC)


def _create_membership(
    *,
    role: OrganizationRole = OrganizationRole.MEMBER,
    created_at: datetime = _DEFAULT_CREATED_AT,
    accepted_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> OrganizationMembership:
    # A small, self-contained factory (not a shared tests/.../factories.py) --
    # mirrors test_organization.py's/test_api_key.py's own local factories.
    #
    # A pending invitation MUST carry an expiry (see the invariant tests at
    # the bottom), so a pending row gets _EXPIRES_AT unless a test chooses
    # its own; an accepted row gets none.
    if accepted_at is None and expires_at is None:
        expires_at = _EXPIRES_AT
    return OrganizationMembership(
        id_=OrganizationMembershipId(uuid4()),
        organization_id=OrganizationId(uuid4()),
        user_id=UserId(uuid4()),
        role=role,
        invited_by_user_id=UserId(uuid4()),
        created_at=UtcDatetime(created_at),
        accepted_at=UtcDatetime(accepted_at) if accepted_at is not None else None,
        expires_at=UtcDatetime(expires_at) if expires_at is not None else None,
    )


def test_a_freshly_invited_membership_is_not_accepted() -> None:
    sut = _create_membership()

    assert sut.is_accepted is False
    assert sut.accepted_at is None


def test_accept_marks_the_membership_as_accepted() -> None:
    sut = _create_membership()
    now = UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))

    sut.accept(now=now)

    assert sut.is_accepted is True
    assert sut.accepted_at == now


def test_a_membership_constructed_with_accepted_at_already_set_is_accepted() -> None:
    # Covers CreateOrganization's shape: the creator's own membership row is
    # constructed already-accepted (role=OWNER), with no accept() call needed.
    accepted_at = UtcDatetime(_DEFAULT_CREATED_AT)

    sut = _create_membership(role=OrganizationRole.OWNER, accepted_at=_DEFAULT_CREATED_AT)

    assert sut.is_accepted is True
    assert sut.accepted_at == accepted_at


# --- Invitation expiry -----------------------------------------------------
# A pending invitation carries an expires_at; the same `now >= expires_at`
# boundary as ApiKey.is_expired() (test_api_key.py), so "expired" means the
# same thing everywhere in this codebase.


def test_a_pending_invitation_keeps_its_expires_at() -> None:
    sut = _create_membership(expires_at=_EXPIRES_AT)

    assert sut.expires_at == UtcDatetime(_EXPIRES_AT)


def test_a_pending_invitation_is_not_expired_before_its_expiry_instant() -> None:
    sut = _create_membership(expires_at=_EXPIRES_AT)

    assert sut.is_expired(UtcDatetime(datetime(2026, 1, 7, 23, 59, tzinfo=UTC))) is False


def test_a_pending_invitation_is_expired_exactly_at_its_expiry_instant() -> None:
    sut = _create_membership(expires_at=_EXPIRES_AT)

    assert sut.is_expired(UtcDatetime(_EXPIRES_AT)) is True


def test_a_pending_invitation_is_expired_after_its_expiry_instant() -> None:
    sut = _create_membership(expires_at=_EXPIRES_AT)

    assert sut.is_expired(UtcDatetime(datetime(2026, 2, 1, tzinfo=UTC))) is True


def test_a_membership_without_expires_at_never_expires() -> None:
    # The creator's own OWNER row is constructed accepted, with no expiry.
    sut = _create_membership(role=OrganizationRole.OWNER, accepted_at=_DEFAULT_CREATED_AT)

    assert sut.expires_at is None
    assert sut.is_expired(UtcDatetime(datetime(2099, 1, 1, tzinfo=UTC))) is False


def test_accepting_clears_expires_at_so_a_membership_never_expires() -> None:
    # Expiry only ever applies to a PENDING invitation -- once accepted, the
    # membership is permanent, however long ago the invitation was sent.
    sut = _create_membership(expires_at=_EXPIRES_AT)

    sut.accept(now=UtcDatetime(datetime(2026, 1, 5, tzinfo=UTC)))

    assert sut.expires_at is None
    assert sut.is_expired(UtcDatetime(datetime(2099, 1, 1, tzinfo=UTC))) is False


# --- Expiry invariant ------------------------------------------------------
# Exactly one of accepted_at/expires_at is set at construction: a pending
# invitation always expires, an accepted membership never does. The
# entity refuses anything else, so a caller that forgets expires_at fails
# loudly instead of silently creating an invitation that lives forever.
# The TTL itself (ORGANIZATION_INVITATION_TTL_DAYS, default 7) is NOT the
# entity's concern -- InviteOrganizationMember computes it from settings.
# Both tests call the constructor directly, bypassing _create_membership's
# own default, since the whole point is the combination it would prevent.


def test_a_pending_invitation_without_expires_at_is_rejected() -> None:
    with pytest.raises(InvalidMembershipExpiryError):
        OrganizationMembership(
            id_=OrganizationMembershipId(uuid4()),
            organization_id=OrganizationId(uuid4()),
            user_id=UserId(uuid4()),
            role=OrganizationRole.MEMBER,
            invited_by_user_id=UserId(uuid4()),
            created_at=UtcDatetime(_DEFAULT_CREATED_AT),
            accepted_at=None,
            expires_at=None,
        )


def test_an_accepted_membership_with_expires_at_is_rejected() -> None:
    with pytest.raises(InvalidMembershipExpiryError):
        OrganizationMembership(
            id_=OrganizationMembershipId(uuid4()),
            organization_id=OrganizationId(uuid4()),
            user_id=UserId(uuid4()),
            role=OrganizationRole.OWNER,
            invited_by_user_id=UserId(uuid4()),
            created_at=UtcDatetime(_DEFAULT_CREATED_AT),
            accepted_at=UtcDatetime(_DEFAULT_CREATED_AT),
            expires_at=UtcDatetime(_EXPIRES_AT),
        )
