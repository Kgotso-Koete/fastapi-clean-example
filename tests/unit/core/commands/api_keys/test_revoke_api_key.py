from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.commands.api_key_exceptions import ApiKeyNotFoundError
from app.core.commands.revoke_api_key import RevokeApiKey, RevokeApiKeyRequest
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeApiKeyRepository, FakeTransactionManager, FakeUtcTimer
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_user


def _make_api_key(*, user_id: UserId, revoked: bool = False) -> ApiKey:
    now = UtcDatetime(datetime.now(UTC))
    api_key = ApiKey(
        id_=ApiKeyId(uuid4()),
        user_id=user_id,
        key_hash=ApiKeyHash("some-hash"),
        key_prefix="ak_abcd1234",
        label=None,
        created_at=now,
        expires_at=UtcDatetime(now.value + timedelta(days=30)),
    )
    if revoked:
        api_key.revoke(now=now)
    return api_key


@pytest.mark.asyncio
async def test_owner_revoking_their_own_key_commits_a_revoked_key() -> None:
    user = create_user()
    api_key = _make_api_key(user_id=user.id_)
    api_key_repository = FakeApiKeyRepository(get_by_id_result=api_key)
    transaction_manager = FakeTransactionManager()
    sut = RevokeApiKey(
        current_user_service=create_current_user_service(user),
        api_key_repository=api_key_repository,
        utc_timer=FakeUtcTimer(UtcDatetime(datetime.now(UTC))),
        transaction_manager=transaction_manager,
    )

    await sut.execute(RevokeApiKeyRequest(api_key_id=api_key.id_))

    assert api_key.is_revoked
    assert transaction_manager.commit_call_count == 1


@pytest.mark.asyncio
async def test_unknown_id_raises_api_key_not_found_error() -> None:
    user = create_user()
    sut = RevokeApiKey(
        current_user_service=create_current_user_service(user),
        api_key_repository=FakeApiKeyRepository(get_by_id_result=None),
        utc_timer=FakeUtcTimer(UtcDatetime(datetime.now(UTC))),
        transaction_manager=FakeTransactionManager(),
    )

    with pytest.raises(ApiKeyNotFoundError):
        await sut.execute(RevokeApiKeyRequest(api_key_id=uuid4()))


@pytest.mark.asyncio
async def test_another_users_key_raises_authorization_error() -> None:
    owner = create_user()
    caller = create_user()
    api_key = _make_api_key(user_id=owner.id_)
    transaction_manager = FakeTransactionManager()
    sut = RevokeApiKey(
        current_user_service=create_current_user_service(caller),
        api_key_repository=FakeApiKeyRepository(get_by_id_result=api_key),
        utc_timer=FakeUtcTimer(UtcDatetime(datetime.now(UTC))),
        transaction_manager=transaction_manager,
    )

    with pytest.raises(AuthorizationError):
        await sut.execute(RevokeApiKeyRequest(api_key_id=api_key.id_))

    # Never revoked, never committed -- the ownership check must happen
    # before any mutation, not merely block the response afterward.
    assert not api_key.is_revoked
    assert transaction_manager.commit_call_count == 0


@pytest.mark.asyncio
async def test_revoking_an_already_revoked_key_is_a_no_op() -> None:
    user = create_user()
    api_key = _make_api_key(user_id=user.id_, revoked=True)
    transaction_manager = FakeTransactionManager()
    sut = RevokeApiKey(
        current_user_service=create_current_user_service(user),
        api_key_repository=FakeApiKeyRepository(get_by_id_result=api_key),
        utc_timer=FakeUtcTimer(UtcDatetime(datetime.now(UTC))),
        transaction_manager=transaction_manager,
    )

    await sut.execute(RevokeApiKeyRequest(api_key_id=api_key.id_))

    # Idempotent: no second commit for an already-revoked key.
    assert transaction_manager.commit_call_count == 0
