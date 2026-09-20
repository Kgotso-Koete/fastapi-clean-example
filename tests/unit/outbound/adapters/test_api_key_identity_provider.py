from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.common.ports.api_key_hasher import ApiKeyHasher
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.adapters.api_key_identity_provider import (
    API_KEY_HEADER_NAME,
    ApiKeyAuthenticationError,
    ApiKeyIdentityProvider,
)

_DEFAULT_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_FIXED_HASH = ApiKeyHash("fixed-hash-for-tests")


def _make_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    # A real, minimal starlette Request built directly from an ASGI scope --
    # ApiKeyIdentityProvider only ever reads request.headers, so nothing
    # else in the scope needs to be realistic. Mirrors
    # tests/unit/inbound/http/errors/test_alerting.py's own _make_request.
    # ASGI header names must already be lowercased bytes -- Starlette's
    # Headers lookup is case-insensitive regardless, but this matches what
    # a real ASGI server actually sends.
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": headers or [],
    }
    return Request(scope)


def _make_request_with_key(raw_key: str = "ak_the-raw-key") -> Request:
    return _make_request([(API_KEY_HEADER_NAME.lower().encode(), raw_key.encode())])


def _create_api_key(
    *,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> ApiKey:
    # A small, self-contained factory (not a shared tests/.../factories.py)
    # since only this file needs it -- mirrors test_api_key.py's own
    # _create_api_key.
    now = _DEFAULT_CREATED_AT
    return ApiKey(
        id_=ApiKeyId(uuid4()),
        user_id=UserId(uuid4()),
        key_hash=_FIXED_HASH,
        key_prefix="ak_deadbeef",
        label="ci",
        created_at=UtcDatetime(now),
        expires_at=UtcDatetime(expires_at or (now + timedelta(days=30))),
        revoked_at=UtcDatetime(revoked_at) if revoked_at is not None else None,
    )


class FakeApiKeyHasher(ApiKeyHasher):
    """Always returns the same fixed hash, regardless of the raw key given --
    these tests only care about what the repository does with that hash,
    never about the hashing algorithm itself (already covered by
    test_hmac_sha256_api_key_hasher.py)."""

    def hash(self, raw_key: str) -> ApiKeyHash:
        return _FIXED_HASH


class FakeUtcTimer(UtcTimer):
    def __init__(self, now: UtcDatetime) -> None:
        self._now = now

    @property
    def now(self) -> UtcDatetime:
        return self._now


class FakeApiKeyRepository(ApiKeyRepository):
    """Returns a fixed ApiKey (or None) for any key_hash asked about --
    good enough since these tests only ever look up one key at a time."""

    def __init__(self, api_key: ApiKey | None) -> None:
        self._api_key = api_key

    def add(self, api_key: ApiKey) -> None:
        raise NotImplementedError

    async def get_by_id(self, api_key_id: ApiKeyId, *, for_update: bool = False) -> ApiKey | None:
        raise NotImplementedError

    async def get_by_key_hash(self, key_hash: ApiKeyHash) -> ApiKey | None:
        return self._api_key

    async def revoke_all_for_user(self, user_id: UserId) -> None:
        raise NotImplementedError

    async def count_active_for_user(self, user_id: UserId) -> int:
        raise NotImplementedError


class FakeTransactionManager(TransactionManager):
    def __init__(self) -> None:
        self.commit_call_count = 0

    async def commit(self) -> None:
        self.commit_call_count += 1


@pytest.mark.asyncio
async def test_valid_key_resolves_to_the_owning_user_and_records_a_use() -> None:
    api_key = _create_api_key()
    transaction_manager = FakeTransactionManager()
    sut = ApiKeyIdentityProvider(
        request=_make_request_with_key(),
        api_key_repository=FakeApiKeyRepository(api_key),
        api_key_hasher=FakeApiKeyHasher(),
        # Well within _create_api_key()'s default 30-day expiry window from
        # its created_at (2026-01-01) -- unlike the other tests below, this
        # one needs the key to actually still be valid.
        utc_timer=FakeUtcTimer(UtcDatetime(datetime(2026, 1, 15, tzinfo=UTC))),
        transaction_manager=transaction_manager,
    )

    user_id = await sut.get_current_user_id()

    assert user_id == api_key.user_id
    # record_use() actually ran on the SAME object the repository returned
    # (not a copy), and the transaction was committed exactly once.
    assert api_key.use_count == 1
    assert api_key.last_used_at is not None
    assert transaction_manager.commit_call_count == 1


@pytest.mark.asyncio
async def test_missing_header_raises_without_recording_a_use() -> None:
    api_key = _create_api_key()
    transaction_manager = FakeTransactionManager()
    sut = ApiKeyIdentityProvider(
        request=_make_request(),  # no X-API-Key header at all
        api_key_repository=FakeApiKeyRepository(api_key),
        api_key_hasher=FakeApiKeyHasher(),
        utc_timer=FakeUtcTimer(UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))),
        transaction_manager=transaction_manager,
    )

    with pytest.raises(ApiKeyAuthenticationError):
        await sut.get_current_user_id()

    assert api_key.use_count == 0
    assert transaction_manager.commit_call_count == 0


@pytest.mark.asyncio
async def test_unknown_hash_raises_without_recording_a_use() -> None:
    transaction_manager = FakeTransactionManager()
    sut = ApiKeyIdentityProvider(
        request=_make_request_with_key("ak_no-such-key"),
        api_key_repository=FakeApiKeyRepository(None),  # no matching row
        api_key_hasher=FakeApiKeyHasher(),
        utc_timer=FakeUtcTimer(UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))),
        transaction_manager=transaction_manager,
    )

    with pytest.raises(ApiKeyAuthenticationError):
        await sut.get_current_user_id()

    assert transaction_manager.commit_call_count == 0


@pytest.mark.asyncio
async def test_revoked_key_raises_without_recording_a_use() -> None:
    # expires_at set far in the future so revocation is the ONLY reason
    # this key fails -- isolates what this test is actually about, rather
    # than incidentally also being expired.
    api_key = _create_api_key(
        revoked_at=datetime(2026, 1, 10, tzinfo=UTC),
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    transaction_manager = FakeTransactionManager()
    sut = ApiKeyIdentityProvider(
        request=_make_request_with_key(),
        api_key_repository=FakeApiKeyRepository(api_key),
        api_key_hasher=FakeApiKeyHasher(),
        utc_timer=FakeUtcTimer(UtcDatetime(datetime(2026, 1, 15, tzinfo=UTC))),
        transaction_manager=transaction_manager,
    )

    with pytest.raises(ApiKeyAuthenticationError):
        await sut.get_current_user_id()

    assert api_key.use_count == 0
    assert transaction_manager.commit_call_count == 0


@pytest.mark.asyncio
async def test_expired_key_raises_without_recording_a_use() -> None:
    api_key = _create_api_key(expires_at=datetime(2026, 1, 2, tzinfo=UTC))
    transaction_manager = FakeTransactionManager()
    sut = ApiKeyIdentityProvider(
        request=_make_request_with_key(),
        api_key_repository=FakeApiKeyRepository(api_key),
        api_key_hasher=FakeApiKeyHasher(),
        # "now" is well after expires_at.
        utc_timer=FakeUtcTimer(UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))),
        transaction_manager=transaction_manager,
    )

    with pytest.raises(ApiKeyAuthenticationError):
        await sut.get_current_user_id()

    assert api_key.use_count == 0
    assert transaction_manager.commit_call_count == 0
