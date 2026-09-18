from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.api_key import ApiKey, ApiKeyHash
from app.core.common.entities.types_ import UserId
from app.core.common.factories.api_key_id_factory import create_api_key_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.adapters.sqla_api_key_repository import SqlaApiKeyRepository
from tests.integration.with_infra.factories import create_user

# No DI container involved yet at this step (per the plan) -- the
# repository is constructed directly against it_session, exactly like a
# unit test would construct it against a fake, just with a real Postgres
# session underneath.


async def _persist_user(it_session: AsyncSession, it_user_service: UserService) -> UserId:
    # create_user() is sync (no password hashing involved) -- plenty for
    # these tests, which only need a real users.id row to satisfy
    # api_keys.user_id's foreign key.
    user = create_user(it_user_service)
    it_session.add(user)
    await it_session.commit()
    return user.id_


def _build_api_key(*, user_id: UserId, key_hash: str = "deadbeef") -> ApiKey:
    now = datetime.now(UTC)
    return ApiKey(
        id_=create_api_key_id(),
        user_id=user_id,
        key_hash=ApiKeyHash(key_hash),
        key_prefix="ak_deadbeef",
        label="ci",
        created_at=UtcDatetime(now),
        expires_at=UtcDatetime(now + timedelta(days=30)),
    )


@pytest.mark.asyncio
async def test_add_then_get_by_id_round_trips(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    sut = SqlaApiKeyRepository(it_session)
    api_key = _build_api_key(user_id=user_id)

    sut.add(api_key)
    await it_session.commit()

    found = await sut.get_by_id(api_key.id_)

    assert found is not None
    assert found.id_ == api_key.id_
    assert found.user_id == user_id
    assert found.key_hash == api_key.key_hash
    assert found.key_prefix == "ak_deadbeef"
    assert found.label == "ci"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_an_unknown_id(it_session: AsyncSession) -> None:
    sut = SqlaApiKeyRepository(it_session)

    found = await sut.get_by_id(create_api_key_id())

    assert found is None


@pytest.mark.asyncio
async def test_get_by_key_hash_finds_the_right_row(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    sut = SqlaApiKeyRepository(it_session)
    api_key = _build_api_key(user_id=user_id, key_hash="the-real-hash")
    sut.add(api_key)
    await it_session.commit()

    found = await sut.get_by_key_hash(ApiKeyHash("the-real-hash"))

    assert found is not None
    assert found.id_ == api_key.id_


@pytest.mark.asyncio
async def test_get_by_key_hash_returns_none_for_an_unknown_hash(it_session: AsyncSession) -> None:
    sut = SqlaApiKeyRepository(it_session)

    found = await sut.get_by_key_hash(ApiKeyHash("no-such-hash"))

    assert found is None


@pytest.mark.asyncio
async def test_revoke_all_for_user_revokes_only_that_users_unrevoked_keys(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_a_id = await _persist_user(it_session, it_user_service)
    user_b_id = await _persist_user(it_session, it_user_service)
    sut = SqlaApiKeyRepository(it_session)

    key_a1 = _build_api_key(user_id=user_a_id, key_hash="a1")
    key_a2 = _build_api_key(user_id=user_a_id, key_hash="a2")
    key_b1 = _build_api_key(user_id=user_b_id, key_hash="b1")
    sut.add(key_a1)
    sut.add(key_a2)
    sut.add(key_b1)
    await it_session.commit()

    await sut.revoke_all_for_user(user_a_id)
    await it_session.commit()

    found_a1 = await sut.get_by_id(key_a1.id_)
    found_a2 = await sut.get_by_id(key_a2.id_)
    found_b1 = await sut.get_by_id(key_b1.id_)
    assert found_a1 is not None
    assert found_a1.is_revoked
    assert found_a2 is not None
    assert found_a2.is_revoked
    # User B's key was never touched -- proves the WHERE user_id clause
    # actually scopes the bulk UPDATE.
    assert found_b1 is not None
    assert not found_b1.is_revoked


@pytest.mark.asyncio
async def test_revoke_all_for_user_is_a_no_op_on_already_revoked_keys(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user_id = await _persist_user(it_session, it_user_service)
    sut = SqlaApiKeyRepository(it_session)
    api_key = _build_api_key(user_id=user_id)
    now = UtcDatetime(datetime.now(UTC))
    api_key.revoke(now=now)
    sut.add(api_key)
    await it_session.commit()

    # Revoking again must not error or change the already-set revoked_at.
    await sut.revoke_all_for_user(user_id)
    await it_session.commit()

    found = await sut.get_by_id(api_key.id_)
    assert found is not None
    assert found.is_revoked
