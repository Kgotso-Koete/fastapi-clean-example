import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembershipId
from app.core.common.entities.types_ import UserId
from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent

# OrganizationInvitationCreatedEvent (docs/plans/9-organizations.md, Step 6b):
# recorded by InviteOrganizationMember, and carrying everything the invitation
# email needs, so SendOrganizationInvitationEmail never queries the database.
# Mirrors test_user_registered.py.


def _event(occurred_at: datetime) -> OrganizationInvitationCreatedEvent:
    return OrganizationInvitationCreatedEvent(
        occurred_at=occurred_at,
        organization_id=OrganizationId(uuid.uuid4()),
        organization_name="Avengers",
        membership_id=OrganizationMembershipId(uuid.uuid4()),
        invitee_user_id=UserId(uuid.uuid4()),
        invitee_email="bruce@example.com",
        inviter_username="tony-stark",
        # A plain string, not OrganizationRole: the payload is JSON, and a
        # plain string comes back from from_payload() exactly as it went in.
        role="admin",
        expires_at=occurred_at + timedelta(days=7),
    )


class TestOrganizationInvitationCreatedEvent:
    def test_event_is_immutable(self) -> None:
        event = _event(datetime.now(UTC))

        with pytest.raises(AttributeError):
            event.role = "owner"  # type: ignore[misc]


class TestOrganizationInvitationCreatedEventPayloadRoundTrip:
    """
    The exact payload a Celery task receives through the outbox, and must
    rebuild the event from.
    """

    def test_to_payload_from_payload_round_trip(self) -> None:
        occurred_at = datetime.now(UTC)
        event = _event(occurred_at)

        payload = event.to_payload()
        reconstructed = OrganizationInvitationCreatedEvent.from_payload(payload)

        # The ids and datetimes become strings; the rest are already strings.
        assert payload == {
            "occurred_at": occurred_at.isoformat(),
            "organization_id": str(event.organization_id),
            "organization_name": "Avengers",
            "membership_id": str(event.membership_id),
            "invitee_user_id": str(event.invitee_user_id),
            "invitee_email": "bruce@example.com",
            "inviter_username": "tony-stark",
            "role": "admin",
            "expires_at": event.expires_at.isoformat(),
        }
        assert reconstructed == event
