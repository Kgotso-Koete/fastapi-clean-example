from abc import abstractmethod
from typing import Protocol

from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationMembershipId
from app.core.common.entities.types_ import UserId


class OrganizationRepository(Protocol):
    """Transactional: commit required."""

    @abstractmethod
    def add(self, organization: Organization) -> None: ...

    @abstractmethod
    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None: ...

    @abstractmethod
    def add_membership(self, membership: OrganizationMembership) -> None: ...

    @abstractmethod
    async def get_membership_by_id(
        self,
        organization_id: OrganizationId,
        membership_id: OrganizationMembershipId,
    ) -> OrganizationMembership | None:
        """
        Scoped to ONE organization on purpose: a membership id belonging to
        a different organization resolves to None, exactly as if it didn't
        exist. Every caller already knows which organization it's acting in
        (the organization_id from the URL), so there is no legitimate need
        for an unscoped lookup -- and without the scoping, an ADMIN of one
        organization could act on another organization's member just by
        knowing that membership's id.
        """
        ...

    @abstractmethod
    async def get_membership_for_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> OrganizationMembership | None:
        """
        This user's row in THIS organization, pending or accepted, or None.
        There's at most one, thanks to the unique (organization_id, user_id)
        constraint. InviteOrganizationMember checks this BEFORE inserting, so
        a duplicate invite becomes MembershipAlreadyExistsError (409), or an
        expired pending row gets refreshed, instead of a raw IntegrityError.
        """
        ...

    @abstractmethod
    async def delete_membership(self, membership: OrganizationMembership) -> None:
        """Staged like add_membership(): the row is only gone once the caller
        commits. Used to decline an invitation, revoke one, remove a member
        or leave an organization."""
        ...

    @abstractmethod
    async def count_owners(self, organization_id: OrganizationId) -> int:
        """Counts this organization's ACCEPTED OWNER memberships only -- a
        pending OWNER invite doesn't count. Used by RemoveOrganizationMember
        to refuse removing the last real owner."""
        ...
