from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.organization_ports import MembershipChecker
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.entities.user import User
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.common.authorization.factories import create_current_user_service

# Shared fakes for the Step 7 membership-management tests
# (RemoveOrganizationMember, ChangeOrganizationMemberRole), which both work on
# a whole organization's worth of memberships and both need count_owners().

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class FakeMembershipChecker(MembershipChecker):
    """The CALLER's role in the organization (None for a non-member) -- what
    CurrentOrganizationService.require_role() authorizes against."""

    def __init__(self, role: OrganizationRole | None) -> None:
        self._role = role

    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        return self._role


class FakeMembershipsRepository(OrganizationRepository):
    """Holds a list of memberships and answers like the real adapter:
    get_membership_by_id() is scoped to one organization, and count_owners()
    counts that organization's ACCEPTED owners only. Records deletions and
    lookups; methods these use cases don't need raise NotImplementedError."""

    def __init__(self, memberships: list[OrganizationMembership]) -> None:
        self.memberships = memberships
        self.deleted: list[OrganizationMembership] = []
        self.lookups: list[tuple[OrganizationId, OrganizationMembershipId]] = []

    def add(self, organization: Organization) -> None:
        raise NotImplementedError

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        raise NotImplementedError

    async def delete(self, organization: Organization) -> None:
        raise NotImplementedError

    def add_membership(self, membership: OrganizationMembership) -> None:
        raise NotImplementedError

    async def get_membership_by_id(
        self,
        organization_id: OrganizationId,
        membership_id: OrganizationMembershipId,
    ) -> OrganizationMembership | None:
        self.lookups.append((organization_id, membership_id))
        for m in self.memberships:
            if m.organization_id == organization_id and m.id_ == membership_id:
                return m
        return None

    async def get_membership_for_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> OrganizationMembership | None:
        raise NotImplementedError

    async def delete_membership(self, membership: OrganizationMembership) -> None:
        self.deleted.append(membership)

    async def count_owners(self, organization_id: OrganizationId) -> int:
        return sum(
            1
            for m in self.memberships
            if m.organization_id == organization_id and m.role == OrganizationRole.OWNER and m.is_accepted
        )


def create_membership(
    *,
    organization_id: OrganizationId,
    user: User,
    role: OrganizationRole,
    accepted: bool = True,
) -> OrganizationMembership:
    # An accepted membership by default; accepted=False makes it a pending
    # invitation that is still valid for another 6 days.
    return OrganizationMembership(
        id_=OrganizationMembershipId(uuid4()),
        organization_id=organization_id,
        user_id=user.id_,
        role=role,
        invited_by_user_id=UserId(uuid4()),
        created_at=UtcDatetime(NOW - timedelta(days=8)),
        accepted_at=UtcDatetime(NOW - timedelta(days=7)) if accepted else None,
        expires_at=None if accepted else UtcDatetime(NOW + timedelta(days=6)),
    )


def create_current_organization_service(
    caller: User,
    caller_role: OrganizationRole | None,
) -> CurrentOrganizationService:
    return CurrentOrganizationService(
        current_user_service=create_current_user_service(caller),
        membership_checker=FakeMembershipChecker(caller_role),
    )
