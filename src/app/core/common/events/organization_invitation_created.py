from dataclasses import dataclass
from datetime import datetime

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembershipId
from app.core.common.entities.types_ import UserId
from app.core.common.events.domain_event import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationInvitationCreatedEvent(DomainEvent):
    """
    Raised when an invitation is created, or an expired one renewed
    (InviteOrganizationMember). Carries everything the invitation email
    needs, so its handler never has to query the database.
    """

    organization_id: OrganizationId
    organization_name: str
    membership_id: OrganizationMembershipId
    invitee_user_id: UserId
    invitee_email: str
    inviter_username: str
    # The offered OrganizationRole's value, kept a plain str: the payload is
    # JSON, and a str comes back from from_payload() exactly as it went in.
    role: str
    expires_at: datetime
