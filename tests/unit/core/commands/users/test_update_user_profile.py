from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.commands.exceptions import (
    EmailAlreadyExistsError,
    PhoneNumberAlreadyExistsError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from app.core.commands.ports.flusher import Flusher
from app.core.commands.ports.user_tx_storage import UserTxStorage
from app.core.commands.update_user_profile import UpdateUserProfile, UpdateUserProfileRequest
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.types_ import UserId, UserRole
from app.core.common.entities.user import User
from app.core.common.exceptions import BaseError, BusinessTypeError
from app.core.common.sentinels import OMITTED, Omitted
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager, FakeUtcTimer
from tests.unit.core.commands.organizations.factories import NOW
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_super_user, create_user

# UpdateUserProfile (docs/plans/10-profile-editing.md, Step 4): a platform
# admin edits another user's username, email, phone number and description.
# It mirrors the original author's SetUserPassword: CanManageRole (target role
# USER) for the caller first, then CanManageSubordinate against the loaded
# target. No current password: the role hierarchy is the authorization. The
# same partial-update rules as UpdateOwnProfile (Step 3).

_USERNAME = "peter-parker"
_EMAIL = "peter.parker@dailybugle.com"
_PHONE_NUMBER = "27821000011"
_DESCRIPTION = "Friendly neighborhood photographer."
_CREATED_AT = UtcDatetime(NOW - timedelta(days=30))


class _FakeFlusher(Flusher):
    """Does nothing, or raises the error it was given -- standing in for
    SqlaFlusher turning a unique-constraint clash into a domain error."""

    def __init__(self, error: BaseError | None = None) -> None:
        self._error = error

    async def flush(self) -> None:
        if self._error is not None:
            raise self._error


class _FakeUserTxStorage(UserTxStorage):
    """Holds users by id; records every lookup, so a test can prove a refused
    caller never got as far as loading anyone."""

    def __init__(self, users: list[User]) -> None:
        self._users = {u.id_: u for u in users}
        self.lookups: list[UserId] = []

    def add(self, user: User) -> None:
        raise NotImplementedError

    async def get_by_id(self, user_id: UserId, *, for_update: bool = False) -> User | None:
        self.lookups.append(user_id)
        return self._users.get(user_id)


def _create_target(role: UserRole) -> User:
    # A super admin can't be made through UserService (system role), hence
    # the original author's separate create_super_user factory.
    if role == UserRole.SUPER_ADMIN:
        target = create_super_user(
            username=Username(_USERNAME),
            email=Email(_EMAIL),
            phone_number=PhoneNumber(_PHONE_NUMBER),
            now=_CREATED_AT,
        )
    else:
        target = create_user(
            username=Username(_USERNAME),
            email=Email(_EMAIL),
            phone_number=PhoneNumber(_PHONE_NUMBER),
            role=role,
            now=_CREATED_AT,
        )
    target.description = Description(_DESCRIPTION)
    return target


class _Harness:
    """A caller with `caller_role` and a target user (peter-parker, with a
    description, last updated 30 days ago) with `target_role`."""

    def __init__(
        self,
        *,
        caller_role: UserRole = UserRole.ADMIN,
        target_role: UserRole = UserRole.USER,
        flush_error: BaseError | None = None,
    ) -> None:
        self.caller = create_super_user() if caller_role == UserRole.SUPER_ADMIN else create_user(role=caller_role)
        self.target = _create_target(target_role)
        self.user_tx_storage = _FakeUserTxStorage([self.caller, self.target])
        self.transaction_manager = FakeTransactionManager()
        self.sut = UpdateUserProfile(
            current_user_service=create_current_user_service(self.caller),
            user_tx_storage=self.user_tx_storage,
            utc_timer=FakeUtcTimer(UtcDatetime(NOW)),
            flusher=_FakeFlusher(flush_error),
            transaction_manager=self.transaction_manager,
        )

    def assert_nothing_changed(self) -> None:
        assert self.target.username == Username(_USERNAME)
        assert self.target.email == Email(_EMAIL)
        assert self.target.phone_number == PhoneNumber(_PHONE_NUMBER)
        assert self.target.description == Description(_DESCRIPTION)
        assert self.target.updated_at == _CREATED_AT
        assert self.transaction_manager.commit_call_count == 0


@pytest.mark.parametrize(
    ("caller_role", "target_role"),
    [
        pytest.param(UserRole.ADMIN, UserRole.USER, id="admin_edits_user"),
        pytest.param(UserRole.SUPER_ADMIN, UserRole.ADMIN, id="super_admin_edits_admin"),
    ],
)
async def test_a_manager_edits_a_subordinate_with_no_password(caller_role: UserRole, target_role: UserRole) -> None:
    # The role hierarchy is the authorization, so even the email changes
    # without the target's password (unlike UpdateOwnProfile).
    h = _Harness(caller_role=caller_role, target_role=target_role)

    response = await h.sut.execute(
        UpdateUserProfileRequest(
            user_id=h.target.id_,
            username="spider-man",
            email="spidey@example.com",
            phone_number="0821000099",
            description="Edited by an admin.",
        )
    )

    assert h.target.username == Username("spider-man")
    assert h.target.email == Email("spidey@example.com")
    assert h.target.phone_number == PhoneNumber("27821000099")
    assert h.target.description == Description("Edited by an admin.")
    assert h.target.updated_at == UtcDatetime(NOW)
    assert h.transaction_manager.commit_call_count == 1
    assert response["id"] == h.target.id_
    assert response["username"] == "spider-man"
    assert response["email"] == "spidey@example.com"
    assert response["phone_number"] == "27821000099"
    assert response["description"] == "Edited by an admin."
    assert response["updated_at"] == NOW


@pytest.mark.parametrize(
    "target_role",
    [
        pytest.param(UserRole.ADMIN, id="another_admin"),
        pytest.param(UserRole.SUPER_ADMIN, id="a_super_admin"),
    ],
)
async def test_an_admin_cannot_edit_their_own_level_or_above(target_role: UserRole) -> None:
    # Otherwise an admin could change a super admin's email and take that
    # account over, or two admins could take each other over.
    h = _Harness(caller_role=UserRole.ADMIN, target_role=target_role)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(UpdateUserProfileRequest(user_id=h.target.id_, description="Should not stick."))

    h.assert_nothing_changed()


async def test_a_plain_user_cannot_use_it_even_on_themselves() -> None:
    # A USER manages no one; they edit themselves through UpdateOwnProfile.
    # Refused by CanManageRole before anyone is even looked up.
    h = _Harness(caller_role=UserRole.USER)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(UpdateUserProfileRequest(user_id=h.caller.id_, description="Via the admin route."))

    assert h.user_tx_storage.lookups == []
    assert h.transaction_manager.commit_call_count == 0


async def test_an_unknown_user_is_not_found() -> None:
    h = _Harness()

    with pytest.raises(UserNotFoundError):
        await h.sut.execute(UpdateUserProfileRequest(user_id=UserId(uuid4()), description="Nobody home."))

    assert h.transaction_manager.commit_call_count == 0


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # Only the description is sent; the other fields are left out and must
        # stay as they are.
        pytest.param("Queens, NY.", Description("Queens, NY."), id="changed"),
        # Decision 3: None clears it.
        pytest.param(None, None, id="cleared"),
    ],
)
async def test_a_field_left_out_is_unchanged_and_none_clears_the_description(
    description: str | None,
    expected: Description | None,
) -> None:
    h = _Harness()

    await h.sut.execute(UpdateUserProfileRequest(user_id=h.target.id_, description=description))

    assert h.target.description == expected
    assert h.target.username == Username(_USERNAME)
    assert h.target.email == Email(_EMAIL)
    assert h.target.phone_number == PhoneNumber(_PHONE_NUMBER)
    assert h.transaction_manager.commit_call_count == 1


@pytest.mark.parametrize(
    ("username", "description"),
    [
        # A valid username alongside an invalid description, and the reverse:
        # nothing may be applied.
        pytest.param("spider-man", "   ", id="blank_description"),
        pytest.param("x", OMITTED, id="too_short_username"),
    ],
)
async def test_an_invalid_value_changes_nothing(username: str | Omitted, description: str | Omitted) -> None:
    h = _Harness()

    with pytest.raises(BusinessTypeError):
        await h.sut.execute(UpdateUserProfileRequest(user_id=h.target.id_, username=username, description=description))

    h.assert_nothing_changed()


@pytest.mark.parametrize(
    "clash",
    [
        pytest.param(UsernameAlreadyExistsError(), id="username"),
        pytest.param(EmailAlreadyExistsError(), id="email"),
        pytest.param(PhoneNumberAlreadyExistsError(), id="phone_number"),
    ],
)
async def test_a_value_another_account_has_surfaces_and_nothing_is_committed(clash: BaseError) -> None:
    h = _Harness(flush_error=clash)

    with pytest.raises(type(clash)):
        await h.sut.execute(UpdateUserProfileRequest(user_id=h.target.id_, username="tony-stark"))

    assert h.transaction_manager.commit_call_count == 0
