import pytest

from app.core.common.entities.user import User
from app.core.common.ports.user_finder import UserFinder
from app.core.common.value_objects.username import Username
from app.main.cli.identity_provider import (
    CliIdentityError,
    CliIdentityProvider,
    CliPassword,
    CliUsername,
)
from tests.unit.core.common.services.factories import create_raw_password, create_user, create_user_service
from tests.unit.core.common.services.stubs import StubPasswordHasher


class FakeUserFinder(UserFinder):
    """Returns a fixed user (or None), regardless of the username asked for."""

    def __init__(self, user: User | None) -> None:
        self._user = user

    async def find_by_username(self, username: Username) -> User | None:
        return self._user


async def test_returns_the_matching_user_id_for_correct_credentials() -> None:
    raw_password = create_raw_password()
    password_hash = await StubPasswordHasher().hash(raw_password)
    user = create_user(password_hash=password_hash)
    provider = CliIdentityProvider(
        username=CliUsername(user.username.value),
        password=CliPassword(raw_password.value.decode()),
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
    )

    user_id = await provider.get_current_user_id()

    assert user_id == user.id_


async def test_raises_cli_identity_error_for_unknown_username() -> None:
    provider = CliIdentityProvider(
        username=CliUsername("does-not-exist"),
        password=CliPassword("irrelevant1"),
        user_finder=FakeUserFinder(None),
        user_service=create_user_service(),
    )

    with pytest.raises(CliIdentityError):
        await provider.get_current_user_id()


async def test_raises_cli_identity_error_for_wrong_password() -> None:
    correct_password = create_raw_password()
    password_hash = await StubPasswordHasher().hash(correct_password)
    user = create_user(password_hash=password_hash)
    provider = CliIdentityProvider(
        username=CliUsername(user.username.value),
        password=CliPassword("definitely-the-wrong-one1"),
        user_finder=FakeUserFinder(user),
        user_service=create_user_service(),
    )

    with pytest.raises(CliIdentityError):
        await provider.get_current_user_id()


async def test_unknown_username_and_wrong_password_raise_the_same_message() -> None:
    """
    A different error message for "no such user" vs. "wrong password" would let
    someone enumerate valid usernames by watching which message they get back.
    """
    correct_password = create_raw_password()
    password_hash = await StubPasswordHasher().hash(correct_password)
    user = create_user(password_hash=password_hash)

    with pytest.raises(CliIdentityError) as unknown_username_exc:
        await CliIdentityProvider(
            username=CliUsername("does-not-exist"),
            password=CliPassword("irrelevant1"),
            user_finder=FakeUserFinder(None),
            user_service=create_user_service(),
        ).get_current_user_id()

    with pytest.raises(CliIdentityError) as wrong_password_exc:
        await CliIdentityProvider(
            username=CliUsername(user.username.value),
            password=CliPassword("definitely-the-wrong-one1"),
            user_finder=FakeUserFinder(user),
            user_service=create_user_service(),
        ).get_current_user_id()

    assert str(unknown_username_exc.value) == str(wrong_password_exc.value)
