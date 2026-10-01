import pytest

from app.core.common.entities.user import User
from app.core.queries.list_my_organizations import (
    ListMyOrganizations,
    ListMyOrganizationsRequest,
    OrganizationSortingField,
)
from app.core.queries.ports.organization_reader import ListMyOrganizationsQm
from app.core.queries.query_support.sorting import SortingOrder
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_user
from tests.unit.core.queries.organization_factories import FakeOrganizationReader

# ListMyOrganizations (docs/plans/9-organizations.md, Step 8): the
# organizations the caller has an ACCEPTED membership in. User-scoped, like
# ListApiKeys: no organization-scoped authorization at all, because "which
# organizations am I in" depends only on who is asking.


def _request(
    *,
    limit: int = 20,
    offset: int = 0,
    sorting_field: OrganizationSortingField = OrganizationSortingField.CREATED_AT,
    sorting_order: SortingOrder = SortingOrder.DESC,
) -> ListMyOrganizationsRequest:
    return ListMyOrganizationsRequest(
        limit=limit,
        offset=offset,
        sorting_field=sorting_field,
        sorting_order=sorting_order,
    )


def _sut(reader: FakeOrganizationReader, caller: User | None = None) -> ListMyOrganizations:
    return ListMyOrganizations(
        current_user_service=create_current_user_service(caller or create_user()),
        organization_reader=reader,
    )


@pytest.mark.asyncio
async def test_asks_the_reader_for_the_current_users_organizations_only() -> None:
    user = create_user()
    reader = FakeOrganizationReader()
    sut = _sut(reader, user)

    await sut.execute(_request())

    assert [call[0] for call in reader.list_for_user_calls] == [user.id_]


@pytest.mark.asyncio
async def test_pagination_and_sorting_reach_the_reader_unchanged() -> None:
    reader = FakeOrganizationReader()
    sut = _sut(reader)

    await sut.execute(
        _request(limit=5, offset=10, sorting_field=OrganizationSortingField.NAME, sorting_order=SortingOrder.ASC)
    )

    _, pagination, sorting = reader.list_for_user_calls[0]
    assert (pagination.limit, pagination.offset) == (5, 10)
    assert (sorting.field, sorting.order) == (OrganizationSortingField.NAME, SortingOrder.ASC)


@pytest.mark.asyncio
async def test_returns_the_readers_result_unchanged() -> None:
    expected = ListMyOrganizationsQm(organizations=[], total=4, limit=20, offset=0)
    reader = FakeOrganizationReader(organizations=expected)

    assert await _sut(reader).execute(_request()) == expected
