import pytest

from app.core.queries.list_api_keys import ApiKeySortingField, ListApiKeys, ListApiKeysRequest
from app.core.queries.ports.api_key_reader import ListApiKeysQm
from app.core.queries.query_support.sorting import SortingOrder
from tests.unit.core.commands.api_keys.factories import FakeApiKeyReader
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_user


def _make_request(
    *,
    limit: int = 20,
    offset: int = 0,
    sorting_field: ApiKeySortingField = ApiKeySortingField.CREATED_AT,
    sorting_order: SortingOrder = SortingOrder.DESC,
) -> ListApiKeysRequest:
    return ListApiKeysRequest(limit=limit, offset=offset, sorting_field=sorting_field, sorting_order=sorting_order)


@pytest.mark.asyncio
async def test_scopes_the_reader_call_to_the_current_user() -> None:
    user = create_user()
    api_key_reader = FakeApiKeyReader()
    sut = ListApiKeys(
        current_user_service=create_current_user_service(user),
        api_key_reader=api_key_reader,
    )

    await sut.execute(_make_request())

    assert len(api_key_reader.list_by_user_calls) == 1
    scoped_user_id, _pagination, _sorting = api_key_reader.list_by_user_calls[0]
    assert scoped_user_id == user.id_


@pytest.mark.asyncio
async def test_pagination_and_sorting_params_pass_through_unchanged() -> None:
    user = create_user()
    api_key_reader = FakeApiKeyReader()
    sut = ListApiKeys(
        current_user_service=create_current_user_service(user),
        api_key_reader=api_key_reader,
    )

    await sut.execute(
        _make_request(limit=5, offset=10, sorting_field=ApiKeySortingField.LABEL, sorting_order=SortingOrder.ASC)
    )

    _user_id, pagination, sorting = api_key_reader.list_by_user_calls[0]
    assert pagination.limit == 5
    assert pagination.offset == 10
    assert sorting.field == ApiKeySortingField.LABEL
    assert sorting.order == SortingOrder.ASC


@pytest.mark.asyncio
async def test_returns_the_readers_result_unchanged() -> None:
    user = create_user()
    expected = ListApiKeysQm(api_keys=[], total=3, limit=20, offset=0)
    api_key_reader = FakeApiKeyReader(list_result=expected)
    sut = ListApiKeys(
        current_user_service=create_current_user_service(user),
        api_key_reader=api_key_reader,
    )

    result = await sut.execute(_make_request())

    assert result == expected
