from datetime import UTC, datetime

import pytest

from app.core.commands.api_key_exceptions import ApiKeyLimitExceededError, InvalidApiKeyCredentialsError
from app.core.commands.issue_api_key import IssueApiKey, IssueApiKeyRequest
from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import (
    FakeApiKeyHasher,
    FakeApiKeyRepository,
    FakeTransactionManager,
    FakeUserFinder,
    FakeUtcTimer,
)
from tests.unit.core.common.services.factories import create_raw_password, create_user, create_user_service
from tests.unit.core.common.services.stubs import StubPasswordHasher

_NOW = UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))
# Comfortably above every existing test's key count -- these tests aren't
# about the limit itself, so a high ceiling keeps it a non-factor.
_MAX_KEYS_PER_USER = 10


def _make_request(
    *,
    identifier: str,
    password: str,
    expires_in_days: int = 30,
    label: str | None = None,
) -> IssueApiKeyRequest:
    return IssueApiKeyRequest(identifier=identifier, password=password, expires_in_days=expires_in_days, label=label)


@pytest.mark.asyncio
async def test_correct_credentials_issue_a_key_with_the_right_expiry() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))
    sut = IssueApiKey(
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=FakeApiKeyRepository(),
        transaction_manager=FakeTransactionManager(),
        max_keys_per_user=_MAX_KEYS_PER_USER,
    )

    response = await sut.execute(
        _make_request(identifier=user.username.value, password=raw_password.value.decode(), expires_in_days=30)
    )

    assert response["raw_key"].startswith("ak_")
    # June has 30 days -- June 1 + 30 days lands exactly on July 1.
    assert response["expires_at"] == datetime(2026, 7, 1, tzinfo=UTC)
    assert response["created_at"] == _NOW.value


@pytest.mark.asyncio
async def test_correct_credentials_with_an_email_identifier_look_up_the_user_by_email() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))
    user_finder = FakeUserFinder(user)
    sut = IssueApiKey(
        user_finder=user_finder,
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=FakeApiKeyRepository(),
        transaction_manager=FakeTransactionManager(),
        max_keys_per_user=_MAX_KEYS_PER_USER,
    )

    response = await sut.execute(_make_request(identifier=user.email.value, password=raw_password.value.decode()))

    assert response["raw_key"].startswith("ak_")
    # An email-shaped identifier must resolve through find_by_email, and
    # never through find_by_username -- proves the branching, not just that
    # "some lookup" happened to return a user.
    assert user_finder.find_by_email_calls == [user.email]
    assert user_finder.find_by_username_calls == []


@pytest.mark.asyncio
async def test_repository_receives_only_the_hash_never_the_raw_key() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))
    api_key_repository = FakeApiKeyRepository()
    sut = IssueApiKey(
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=api_key_repository,
        transaction_manager=FakeTransactionManager(),
        max_keys_per_user=_MAX_KEYS_PER_USER,
    )

    response = await sut.execute(_make_request(identifier=user.username.value, password=raw_password.value.decode()))

    assert len(api_key_repository.added) == 1
    stored = api_key_repository.added[0]
    assert stored.key_hash != response["raw_key"]
    assert stored.key_hash == f"hashed:{response['raw_key']}"


@pytest.mark.asyncio
async def test_unknown_username_and_wrong_password_raise_the_same_message() -> None:
    """
    A different error message for "no such user" vs. "wrong password" would
    let a caller enumerate valid usernames by watching which message they
    get back -- same principle CliIdentityProvider's own test already
    establishes.
    """
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))

    with pytest.raises(InvalidApiKeyCredentialsError) as unknown_username_exc:
        await IssueApiKey(
            user_finder=FakeUserFinder(None),
            user_service=create_user_service(),
            utc_timer=FakeUtcTimer(_NOW),
            api_key_hasher=FakeApiKeyHasher(),
            api_key_repository=FakeApiKeyRepository(),
            transaction_manager=FakeTransactionManager(),
            max_keys_per_user=_MAX_KEYS_PER_USER,
        ).execute(_make_request(identifier="does-not-exist", password="irrelevant1"))

    with pytest.raises(InvalidApiKeyCredentialsError) as wrong_password_exc:
        await IssueApiKey(
            user_finder=FakeUserFinder(user),
            user_service=create_user_service(),
            utc_timer=FakeUtcTimer(_NOW),
            api_key_hasher=FakeApiKeyHasher(),
            api_key_repository=FakeApiKeyRepository(),
            transaction_manager=FakeTransactionManager(),
            max_keys_per_user=_MAX_KEYS_PER_USER,
        ).execute(_make_request(identifier=user.username.value, password="definitely-the-wrong-one1"))

    assert str(unknown_username_exc.value) == str(wrong_password_exc.value)


@pytest.mark.asyncio
async def test_inactive_user_raises_a_distinct_message_and_persists_nothing() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password), is_active=False)
    api_key_repository = FakeApiKeyRepository()
    transaction_manager = FakeTransactionManager()
    sut = IssueApiKey(
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=api_key_repository,
        transaction_manager=transaction_manager,
        max_keys_per_user=_MAX_KEYS_PER_USER,
    )

    with pytest.raises(InvalidApiKeyCredentialsError) as inactive_exc:
        await sut.execute(_make_request(identifier=user.username.value, password=raw_password.value.decode()))

    assert api_key_repository.added == []
    assert transaction_manager.commit_call_count == 0

    # ...and it's a genuinely different message from the credentials-wrong
    # case, since "your account is inactive" isn't a username-enumeration
    # risk the way "no such user" vs "wrong password" is -- there's no
    # ambiguity to hide once the caller already proved they know the
    # correct password.
    with pytest.raises(InvalidApiKeyCredentialsError) as wrong_password_exc:
        await IssueApiKey(
            user_finder=FakeUserFinder(create_user(password_hash=await StubPasswordHasher().hash(raw_password))),
            user_service=create_user_service(),
            utc_timer=FakeUtcTimer(_NOW),
            api_key_hasher=FakeApiKeyHasher(),
            api_key_repository=FakeApiKeyRepository(),
            transaction_manager=FakeTransactionManager(),
            max_keys_per_user=_MAX_KEYS_PER_USER,
        ).execute(_make_request(identifier=user.username.value, password="definitely-the-wrong-one1"))
    assert str(inactive_exc.value) != str(wrong_password_exc.value)


@pytest.mark.asyncio
async def test_out_of_range_expiry_raises_before_anything_is_persisted() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))
    api_key_repository = FakeApiKeyRepository()
    transaction_manager = FakeTransactionManager()
    sut = IssueApiKey(
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=api_key_repository,
        transaction_manager=transaction_manager,
        max_keys_per_user=_MAX_KEYS_PER_USER,
    )

    with pytest.raises(BusinessTypeError):
        await sut.execute(
            _make_request(identifier=user.username.value, password=raw_password.value.decode(), expires_in_days=9999)
        )

    assert api_key_repository.added == []
    assert transaction_manager.commit_call_count == 0


@pytest.mark.asyncio
async def test_raises_when_the_user_already_has_the_maximum_number_of_active_keys() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))
    api_key_repository = FakeApiKeyRepository(count_active_for_user_result=2)
    transaction_manager = FakeTransactionManager()
    sut = IssueApiKey(
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=api_key_repository,
        transaction_manager=transaction_manager,
        max_keys_per_user=2,
    )

    with pytest.raises(ApiKeyLimitExceededError):
        await sut.execute(_make_request(identifier=user.username.value, password=raw_password.value.decode()))

    # No raw key generated (even to discard) and no partial write -- same
    # discipline as the out-of-range-expiry case above.
    assert api_key_repository.added == []
    assert transaction_manager.commit_call_count == 0
    assert api_key_repository.count_active_for_user_calls == [user.id_]


@pytest.mark.asyncio
async def test_issues_a_key_when_the_user_is_one_below_the_limit() -> None:
    raw_password = create_raw_password()
    user = create_user(password_hash=await StubPasswordHasher().hash(raw_password))
    sut = IssueApiKey(
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
        utc_timer=FakeUtcTimer(_NOW),
        api_key_hasher=FakeApiKeyHasher(),
        api_key_repository=FakeApiKeyRepository(count_active_for_user_result=1),
        transaction_manager=FakeTransactionManager(),
        max_keys_per_user=2,
    )

    response = await sut.execute(_make_request(identifier=user.username.value, password=raw_password.value.decode()))

    assert response["raw_key"].startswith("ak_")
