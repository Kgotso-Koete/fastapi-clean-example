from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.queries.get_api_key_usage_stats import (
    ApiKeyNotFoundError,
    GetApiKeyUsageStats,
    GetApiKeyUsageStatsRequest,
)
from app.core.queries.ports.api_key_reader import ApiKeyUsageStatsQm
from tests.unit.core.commands.api_keys.factories import FakeApiKeyReader
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_user


def _make_stats(*, user_id: object) -> ApiKeyUsageStatsQm:
    now = datetime.now(UTC)
    return ApiKeyUsageStatsQm(
        id=uuid4(),
        user_id=user_id,  # type: ignore[typeddict-item]
        key_prefix="ak_abcd1234",
        label=None,
        use_count=3,
        last_used_at=now,
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        revoked_at=None,
    )


@pytest.mark.asyncio
async def test_happy_path_returns_the_readers_result_unchanged() -> None:
    user = create_user()
    expected = _make_stats(user_id=user.id_)
    sut = GetApiKeyUsageStats(
        current_user_service=create_current_user_service(user),
        api_key_reader=FakeApiKeyReader(usage_stats_result=expected),
    )

    result = await sut.execute(GetApiKeyUsageStatsRequest(api_key_id=expected["id"]))

    assert result == expected


@pytest.mark.asyncio
async def test_unknown_id_raises_api_key_not_found_error() -> None:
    user = create_user()
    sut = GetApiKeyUsageStats(
        current_user_service=create_current_user_service(user),
        api_key_reader=FakeApiKeyReader(usage_stats_result=None),
    )

    with pytest.raises(ApiKeyNotFoundError):
        await sut.execute(GetApiKeyUsageStatsRequest(api_key_id=uuid4()))


@pytest.mark.asyncio
async def test_another_users_stats_row_raises_authorization_error() -> None:
    owner = create_user()
    caller = create_user()
    stats = _make_stats(user_id=owner.id_)
    sut = GetApiKeyUsageStats(
        current_user_service=create_current_user_service(caller),
        api_key_reader=FakeApiKeyReader(usage_stats_result=stats),
    )

    with pytest.raises(AuthorizationError):
        await sut.execute(GetApiKeyUsageStatsRequest(api_key_id=stats["id"]))
