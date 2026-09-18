from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime

_DEFAULT_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _create_api_key(
    *,
    created_at: datetime = _DEFAULT_CREATED_AT,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> ApiKey:
    # A small, self-contained factory (not a shared tests/.../factories.py)
    # since only this file needs it -- mirrors how the value_objects tests
    # build their own inputs inline rather than sharing a fixture module.
    # use_count/last_used_at are deliberately left at their defaults here --
    # the usage-analytics tests below construct their own expectations
    # around those defaults rather than this factory hardcoding them.
    return ApiKey(
        id_=ApiKeyId(uuid4()),
        user_id=UserId(uuid4()),
        key_hash=ApiKeyHash("deadbeef"),
        key_prefix="ak_deadbeef",
        label="ci",
        created_at=UtcDatetime(created_at),
        expires_at=UtcDatetime(expires_at or (created_at + timedelta(days=30))),
        revoked_at=UtcDatetime(revoked_at) if revoked_at is not None else None,
    )


def test_new_key_is_not_revoked() -> None:
    sut = _create_api_key()

    assert sut.is_revoked is False


def test_revoke_marks_the_key_as_revoked() -> None:
    sut = _create_api_key()
    now = UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))

    sut.revoke(now=now)

    assert sut.is_revoked is True
    assert sut.revoked_at == now


def test_is_expired_is_false_before_the_expiry_instant() -> None:
    expires_at = datetime(2026, 2, 1, tzinfo=UTC)
    sut = _create_api_key(expires_at=expires_at)
    just_before = UtcDatetime(expires_at - timedelta(seconds=1))

    assert sut.is_expired(just_before) is False


def test_is_expired_is_true_exactly_at_the_expiry_instant() -> None:
    # Boundary is inclusive: a key must not still be usable at the exact
    # instant it expires.
    expires_at = datetime(2026, 2, 1, tzinfo=UTC)
    sut = _create_api_key(expires_at=expires_at)
    at_expiry = UtcDatetime(expires_at)

    assert sut.is_expired(at_expiry) is True


def test_is_expired_is_true_after_the_expiry_instant() -> None:
    expires_at = datetime(2026, 2, 1, tzinfo=UTC)
    sut = _create_api_key(expires_at=expires_at)
    just_after = UtcDatetime(expires_at + timedelta(seconds=1))

    assert sut.is_expired(just_after) is True


# --- Usage analytics (use_count / last_used_at / record_use()) ---
# See docs/plans/8-public-api-key-auth.md's "Usage analytics" section for
# why this is a plain counter/timestamp on the same aggregate rather than
# a domain event.


def test_new_key_has_no_recorded_usage() -> None:
    sut = _create_api_key()

    assert sut.use_count == 0
    assert sut.last_used_at is None


def test_record_use_increments_use_count_and_sets_last_used_at() -> None:
    sut = _create_api_key()
    now = UtcDatetime(datetime(2026, 3, 1, tzinfo=UTC))

    sut.record_use(now=now)

    assert sut.use_count == 1
    assert sut.last_used_at == now


def test_record_use_called_twice_increments_to_two_and_updates_last_used_at_to_the_second_call() -> None:
    sut = _create_api_key()
    first_use = UtcDatetime(datetime(2026, 3, 1, tzinfo=UTC))
    second_use = UtcDatetime(datetime(2026, 3, 2, tzinfo=UTC))

    sut.record_use(now=first_use)
    sut.record_use(now=second_use)

    assert sut.use_count == 2
    # last_used_at reflects only the most recent use, not the first one.
    assert sut.last_used_at == second_use
