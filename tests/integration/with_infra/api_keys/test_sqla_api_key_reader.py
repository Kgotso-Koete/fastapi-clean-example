from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.api_key import ApiKey, ApiKeyHash
from app.core.common.entities.types_ import UserId
from app.core.common.factories.api_key_id_factory import create_api_key_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams
from app.outbound.adapters.sqla_api_key_reader import SqlaApiKeyReader
from tests.integration.with_infra.factories import create_user

_DEFAULT_PAGINATION = OffsetPaginationParams(limit=50, offset=0)
_SORT_BY_CREATED_AT_ASC = SortingParams(field="created_at", order=SortingOrder.ASC)


async def _persist_user(it_session: AsyncSession, it_user_service: UserService) -> UserId:
    user = create_user(it_user_service)
    it_session.add(user)
    await it_session.commit()
    return user.id_


def _build_api_key(
    *,
    user_id: UserId,
    key_hash: str = "deadbeef",
    created_at: datetime | None = None,
) -> ApiKey:
    now = created_at or datetime.now(UTC)
    return ApiKey(
        id_=create_api_key_id(),
        user_id=user_id,
        key_hash=ApiKeyHash(key_hash),
        key_prefix=f"ak_{key_hash[:8]}",
        label="ci",
        created_at=UtcDatetime(now),
        expires_at=UtcDatetime(now + timedelta(days=30)),
    )


@pytest.mark.asyncio
async def test_list_by_user_returns_only_that_users_keys(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_a_id = await _persist_user(it_session, it_user_service)
    user_b_id = await _persist_user(it_session, it_user_service)
    it_session.add(_build_api_key(user_id=user_a_id, key_hash="a1"))
    it_session.add(_build_api_key(user_id=user_b_id, key_hash="b1"))
    await it_session.commit()
    sut = SqlaApiKeyReader(it_session)

    result = await sut.list_by_user(user_a_id, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    assert result["total"] == 1
    assert [k["key_prefix"] for k in result["api_keys"]] == ["ak_a1"]


@pytest.mark.asyncio
async def test_list_by_user_paginates_and_reports_total(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    base = datetime.now(UTC)
    for i, key_hash in enumerate(["k1", "k2", "k3"]):
        it_session.add(_build_api_key(user_id=user_id, key_hash=key_hash, created_at=base + timedelta(seconds=i)))
    await it_session.commit()
    sut = SqlaApiKeyReader(it_session)

    page_1 = await sut.list_by_user(
        user_id, pagination=OffsetPaginationParams(limit=2, offset=0), sorting=_SORT_BY_CREATED_AT_ASC
    )
    page_2 = await sut.list_by_user(
        user_id, pagination=OffsetPaginationParams(limit=2, offset=2), sorting=_SORT_BY_CREATED_AT_ASC
    )

    # total reflects the full matching set, not just the page size --
    # both pages must agree on it.
    assert page_1["total"] == 3
    assert page_2["total"] == 3
    assert [k["key_prefix"] for k in page_1["api_keys"]] == ["ak_k1", "ak_k2"]
    assert [k["key_prefix"] for k in page_2["api_keys"]] == ["ak_k3"]


@pytest.mark.asyncio
async def test_list_by_user_sorts_descending_when_requested(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    base = datetime.now(UTC)
    it_session.add(_build_api_key(user_id=user_id, key_hash="oldest", created_at=base))
    it_session.add(_build_api_key(user_id=user_id, key_hash="newest", created_at=base + timedelta(seconds=1)))
    await it_session.commit()
    sut = SqlaApiKeyReader(it_session)

    result = await sut.list_by_user(
        user_id,
        pagination=_DEFAULT_PAGINATION,
        sorting=SortingParams(field="created_at", order=SortingOrder.DESC),
    )

    assert [k["key_prefix"] for k in result["api_keys"]] == ["ak_newest", "ak_oldest"]


@pytest.mark.asyncio
async def test_list_by_user_returns_empty_with_correct_total_for_a_user_with_no_keys(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    sut = SqlaApiKeyReader(it_session)

    result = await sut.list_by_user(user_id, pagination=_DEFAULT_PAGINATION, sorting=_SORT_BY_CREATED_AT_ASC)

    assert result == {"api_keys": [], "total": 0, "limit": 50, "offset": 0}


@pytest.mark.asyncio
async def test_get_usage_stats_by_id_returns_the_right_stats(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    api_key = _build_api_key(user_id=user_id, key_hash="stats-me")
    now = UtcDatetime(datetime.now(UTC))
    api_key.record_use(now=now)
    api_key.record_use(now=now)
    it_session.add(api_key)
    await it_session.commit()
    sut = SqlaApiKeyReader(it_session)

    stats = await sut.get_usage_stats_by_id(api_key.id_)

    assert stats is not None
    assert stats["id"] == api_key.id_
    assert stats["user_id"] == user_id
    assert stats["use_count"] == 2
    assert stats["last_used_at"] is not None


@pytest.mark.asyncio
async def test_get_usage_stats_by_id_returns_none_for_an_unknown_id(it_session: AsyncSession) -> None:
    sut = SqlaApiKeyReader(it_session)

    stats = await sut.get_usage_stats_by_id(create_api_key_id())

    assert stats is None


@pytest.mark.asyncio
async def test_get_usage_stats_by_id_is_not_scoped_by_owner(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Deliberately unscoped, unlike list_by_user -- ownership is checked by
    # GetApiKeyUsageStats itself (404-vs-403), not filtered out here. See
    # the port's own docstring.
    owner_id = await _persist_user(it_session, it_user_service)
    api_key = _build_api_key(user_id=owner_id, key_hash="someone-elses-key")
    it_session.add(api_key)
    await it_session.commit()
    sut = SqlaApiKeyReader(it_session)

    stats = await sut.get_usage_stats_by_id(api_key.id_)

    assert stats is not None
    assert stats["user_id"] == owner_id
