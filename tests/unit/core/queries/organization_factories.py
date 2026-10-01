from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.queries.ports.organization_reader import (
    ListMyInvitationsQm,
    ListMyOrganizationsQm,
    ListOrganizationMembersQm,
    OrganizationReader,
)
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingParams

# Shared fake for the organization query tests (ListMyOrganizations,
# ListOrganizationMembers, ListMyInvitations), like FakeApiKeyReader is for
# the API key queries.

type ReaderCall[T] = tuple[T, OffsetPaginationParams, SortingParams]


class FakeOrganizationReader(OrganizationReader):
    """Returns fixed results whatever is asked, and records every call's
    arguments, so a test can prove WHOSE data was asked for and that the
    pagination/sorting reached the reader unchanged."""

    def __init__(
        self,
        *,
        organizations: ListMyOrganizationsQm | None = None,
        members: ListOrganizationMembersQm | None = None,
        invitations: ListMyInvitationsQm | None = None,
    ) -> None:
        self._organizations = organizations or ListMyOrganizationsQm(organizations=[], total=0, limit=0, offset=0)
        self._members = members or ListOrganizationMembersQm(members=[], member_count=0, total=0, limit=0, offset=0)
        self._invitations = invitations or ListMyInvitationsQm(invitations=[], total=0, limit=0, offset=0)
        self.list_for_user_calls: list[ReaderCall[UserId]] = []
        self.list_members_calls: list[ReaderCall[OrganizationId]] = []
        self.list_invitations_for_user_calls: list[ReaderCall[UserId]] = []

    async def list_for_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListMyOrganizationsQm:
        self.list_for_user_calls.append((user_id, pagination, sorting))
        return self._organizations

    async def list_members(
        self,
        organization_id: OrganizationId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListOrganizationMembersQm:
        self.list_members_calls.append((organization_id, pagination, sorting))
        return self._members

    async def list_invitations_for_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListMyInvitationsQm:
        self.list_invitations_for_user_calls.append((user_id, pagination, sorting))
        return self._invitations
