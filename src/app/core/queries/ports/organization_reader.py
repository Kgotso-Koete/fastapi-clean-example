from abc import abstractmethod
from datetime import datetime
from typing import Protocol, TypedDict
from uuid import UUID

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.entities.types_ import UserId
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingParams


class OrganizationQm(TypedDict):
    id: UUID
    name: str
    description: str  # mandatory: every organization explains itself
    role: OrganizationRole  # the CALLER's role in this organization
    member_count: int  # accepted memberships only -- see the plan's "Member count" note
    created_at: datetime


class ListMyOrganizationsQm(TypedDict):
    organizations: list[OrganizationQm]
    total: int
    limit: int
    offset: int


class OrganizationMemberQm(TypedDict):
    # username is deliberately the ONLY personal detail here -- every member
    # of an organization can list its members, so email/phone never belong
    # in this row.
    membership_id: UUID
    username: str
    role: OrganizationRole
    accepted_at: datetime | None  # None = a still-pending invitation
    # When a pending invitation lapses (None for a real member), so admins can
    # see which invitations have expired and need re-sending.
    expires_at: datetime | None
    created_at: datetime


class ListOrganizationMembersQm(TypedDict):
    members: list[OrganizationMemberQm]
    # member_count counts accepted MEMBERS; total counts the listed ROWS,
    # which include pending invitations -- the two differ on purpose.
    member_count: int
    total: int
    limit: int
    offset: int


class InvitationQm(TypedDict):
    # membership_id + organization_id are exactly what the accept route
    # (/organizations/{organization_id}/members/{membership_id}/accept/) needs.
    membership_id: UUID
    organization_id: UUID
    organization_name: str
    # The invitee isn't a member yet, so this is where they learn what the
    # organization is before deciding to accept.
    organization_description: str
    role: OrganizationRole  # the role being offered
    invited_by_username: str
    created_at: datetime
    expires_at: datetime  # the invitee's deadline to accept


class ListMyInvitationsQm(TypedDict):
    invitations: list[InvitationQm]
    total: int
    limit: int
    offset: int


class OrganizationReader(Protocol):
    """
    Read-only, and performs NO authorization of its own -- who may call
    each query is enforced by the query use cases, exactly like
    ApiKeyReader leaves ownership checks to GetApiKeyUsageStats.
    """

    @abstractmethod
    async def list_for_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListMyOrganizationsQm:
        """The organizations this user has an ACCEPTED membership in."""
        ...

    @abstractmethod
    async def list_members(
        self,
        organization_id: OrganizationId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListOrganizationMembersQm:
        """Every membership row of this organization, accepted AND pending."""
        ...

    @abstractmethod
    async def list_invitations_for_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListMyInvitationsQm:
        """This user's own PENDING, UNEXPIRED invitations, across every
        organization -- an expired one can no longer be accepted."""
        ...
