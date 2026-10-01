import pytest

from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.queries.list_organization_members import (
    ListOrganizationMembers,
    ListOrganizationMembersRequest,
    MemberSortingField,
)
from app.core.queries.ports.organization_reader import ListOrganizationMembersQm
from app.core.queries.query_support.sorting import SortingOrder
from tests.unit.core.commands.organizations.factories import create_current_organization_service
from tests.unit.core.common.services.factories import create_user
from tests.unit.core.queries.organization_factories import FakeOrganizationReader

# ListOrganizationMembers (docs/plans/9-organizations.md, Step 8): every
# membership row of ONE organization, accepted and pending. Organization-
# scoped, at the lowest role: any member (not just an OWNER/ADMIN) may see who
# else is in their organization; a non-member gets 404, never the list.


def _request(
    organization_id: OrganizationId,
    *,
    limit: int = 20,
    offset: int = 0,
    sorting_field: MemberSortingField = MemberSortingField.CREATED_AT,
    sorting_order: SortingOrder = SortingOrder.ASC,
) -> ListOrganizationMembersRequest:
    return ListOrganizationMembersRequest(
        organization_id=organization_id,
        limit=limit,
        offset=offset,
        sorting_field=sorting_field,
        sorting_order=sorting_order,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_role", [OrganizationRole.MEMBER, OrganizationRole.ADMIN, OrganizationRole.OWNER])
async def test_any_member_lists_this_organizations_members(caller_role: OrganizationRole) -> None:
    organization_id = create_organization_id()
    expected = ListOrganizationMembersQm(members=[], member_count=3, total=4, limit=20, offset=0)
    reader = FakeOrganizationReader(members=expected)
    sut = ListOrganizationMembers(
        current_organization_service=create_current_organization_service(create_user(), caller_role),
        organization_reader=reader,
    )

    result = await sut.execute(_request(organization_id))

    # Asked about THIS organization, and the reader's answer came back as-is.
    assert [call[0] for call in reader.list_members_calls] == [organization_id]
    assert result == expected


@pytest.mark.asyncio
async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    reader = FakeOrganizationReader()
    sut = ListOrganizationMembers(
        current_organization_service=create_current_organization_service(create_user(), None),
        organization_reader=reader,
    )

    with pytest.raises(OrganizationNotFoundError):
        await sut.execute(_request(create_organization_id()))

    # Refused before anything is read.
    assert reader.list_members_calls == []


@pytest.mark.asyncio
async def test_pagination_and_sorting_reach_the_reader_unchanged() -> None:
    reader = FakeOrganizationReader()
    sut = ListOrganizationMembers(
        current_organization_service=create_current_organization_service(create_user(), OrganizationRole.MEMBER),
        organization_reader=reader,
    )

    await sut.execute(
        _request(
            create_organization_id(),
            limit=5,
            offset=10,
            sorting_field=MemberSortingField.ROLE,
            sorting_order=SortingOrder.DESC,
        )
    )

    _, pagination, sorting = reader.list_members_calls[0]
    assert (pagination.limit, pagination.offset) == (5, 10)
    assert (sorting.field, sorting.order) == (MemberSortingField.ROLE, SortingOrder.DESC)
