from datetime import timedelta

import pytest

from app.core.commands.exceptions import (
    EmailAlreadyExistsError,
    PhoneNumberAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from app.core.commands.ports.flusher import Flusher
from app.core.common.exceptions import BaseError, BusinessTypeError
from app.core.common.sentinels import OMITTED, Omitted
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.auth_ctx.exceptions import ReAuthenticationError
from app.outbound.auth_ctx.handlers.update_own_profile import UpdateOwnProfile, UpdateOwnProfileRequest
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager, FakeUtcTimer
from tests.unit.core.commands.organizations.factories import NOW
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_user, create_user_service
from tests.unit.core.common.services.stubs import StubPasswordHasher

# UpdateOwnProfile (docs/plans/10-profile-editing.md, Step 3): a logged-in user
# edits their own username, email, phone number and description. It lives
# beside the original author's ChangePassword, the same kind of operation: your
# own login identifiers, behind your current password. A partial update: a
# field left out (OMITTED) stays as it is; the description can be cleared with
# None; every value is validated before anything changes; a changed email
# needs the right current password (missing or wrong: the original author's
# ReAuthenticationError); a value another account already has surfaces from
# the flush as the existing *AlreadyExistsError.

_PASSWORD = "SpideySense2024!"
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


class _Harness:
    """peter-parker, logged in, with a description, last updated 30 days ago.
    Call set_known_password() for tests that re-authenticate."""

    def __init__(self, *, flush_error: BaseError | None = None) -> None:
        self.user = create_user(
            username=Username(_USERNAME),
            email=Email(_EMAIL),
            phone_number=PhoneNumber(_PHONE_NUMBER),
            now=_CREATED_AT,
        )
        self.user.description = Description(_DESCRIPTION)
        self.transaction_manager = FakeTransactionManager()
        self.sut = UpdateOwnProfile(
            current_user_service=create_current_user_service(self.user),
            user_service=create_user_service(),
            utc_timer=FakeUtcTimer(UtcDatetime(NOW)),
            flusher=_FakeFlusher(flush_error),
            transaction_manager=self.transaction_manager,
        )

    async def set_known_password(self) -> None:
        # The stub hasher is deterministic, so a hash made from _PASSWORD here
        # is what is_password_valid() checks against, for real.
        self.user.password_hash = await StubPasswordHasher().hash(RawPassword(_PASSWORD))

    def assert_nothing_changed(self) -> None:
        assert self.user.username == Username(_USERNAME)
        assert self.user.email == Email(_EMAIL)
        assert self.user.phone_number == PhoneNumber(_PHONE_NUMBER)
        assert self.user.description == Description(_DESCRIPTION)
        assert self.user.updated_at == _CREATED_AT
        assert self.transaction_manager.commit_call_count == 0


async def test_every_field_sent_is_changed() -> None:
    h = _Harness()
    await h.set_known_password()

    response = await h.sut.execute(
        UpdateOwnProfileRequest(
            username="spider-man",
            email="spidey@example.com",
            phone_number="0821000099",
            description="Your friendly neighborhood Spider-Man.",
            current_password=_PASSWORD,
        )
    )

    assert h.user.username == Username("spider-man")
    assert h.user.email == Email("spidey@example.com")
    assert h.user.phone_number == PhoneNumber("27821000099")
    assert h.user.description == Description("Your friendly neighborhood Spider-Man.")
    assert h.user.updated_at == UtcDatetime(NOW)
    assert h.transaction_manager.commit_call_count == 1
    # The response is the updated profile as the existing UserQm, as SignUp
    # returns it: values as stored (the phone number in its country-code form).
    assert response.id == h.user.id_
    assert response.username == "spider-man"
    assert response.email == "spidey@example.com"
    assert response.phone_number == "27821000099"
    assert response.description == "Your friendly neighborhood Spider-Man."
    assert response.updated_at == NOW


@pytest.mark.parametrize(
    "request_",
    [
        pytest.param(UpdateOwnProfileRequest(username="spider-man"), id="only_username"),
        pytest.param(UpdateOwnProfileRequest(phone_number="0821000099"), id="only_phone_number"),
        pytest.param(UpdateOwnProfileRequest(description="Queens, NY."), id="only_description"),
    ],
)
async def test_a_field_left_out_is_unchanged(request_: UpdateOwnProfileRequest) -> None:
    # PATCH changes only what's sent: a client fixing one field must never
    # wipe the others by leaving them out.
    h = _Harness()

    await h.sut.execute(request_)

    if request_.username is OMITTED:
        assert h.user.username == Username(_USERNAME)
    if request_.phone_number is OMITTED:
        assert h.user.phone_number == PhoneNumber(_PHONE_NUMBER)
    if request_.description is OMITTED:
        assert h.user.description == Description(_DESCRIPTION)
    assert h.user.email == Email(_EMAIL)
    assert h.transaction_manager.commit_call_count == 1


async def test_none_clears_the_description() -> None:
    # Decision 3: null clears it; it's never confused with leaving it out.
    h = _Harness()

    response = await h.sut.execute(UpdateOwnProfileRequest(description=None))

    assert h.user.description is None
    assert response.description is None


async def test_sending_nothing_returns_the_profile_unchanged() -> None:
    # An empty PATCH is still valid: nothing changes, not even updated_at.
    h = _Harness()

    response = await h.sut.execute(UpdateOwnProfileRequest())

    assert response.username == _USERNAME
    assert response.description == _DESCRIPTION
    assert h.user.updated_at == _CREATED_AT


@pytest.mark.parametrize(
    ("username", "email", "phone_number", "description"),
    [
        # Each sends one valid change (the username) alongside one invalid
        # value: nothing may be applied, because everything is validated
        # before anything changes.
        pytest.param("spider-man", OMITTED, OMITTED, "   ", id="blank_description"),
        pytest.param("x", OMITTED, OMITTED, OMITTED, id="too_short_username"),
        pytest.param("spider-man", "not-an-email", OMITTED, OMITTED, id="bad_email"),
        pytest.param("spider-man", OMITTED, "+44 20 7946 0958", OMITTED, id="non_south_african_phone_number"),
    ],
)
async def test_an_invalid_value_changes_nothing(
    username: str | Omitted,
    email: str | Omitted,
    phone_number: str | Omitted,
    description: str | Omitted,
) -> None:
    h = _Harness()
    await h.set_known_password()

    with pytest.raises(BusinessTypeError):
        await h.sut.execute(
            UpdateOwnProfileRequest(
                username=username,
                email=email,
                phone_number=phone_number,
                description=description,
                current_password=_PASSWORD,
            )
        )

    h.assert_nothing_changed()


@pytest.mark.parametrize(
    "current_password",
    [
        pytest.param(None, id="missing"),
        pytest.param("NotMyPassword123!", id="wrong"),
    ],
)
async def test_a_new_email_without_the_right_current_password_is_refused(current_password: str | None) -> None:
    # Decision 2: email is a login identifier and there's no email
    # verification yet, so whoever holds the session must also know the
    # password (OWASP: re-authenticate before changing an account's email).
    # Missing and wrong are one rule, answered as ChangePassword answers.
    h = _Harness()
    await h.set_known_password()

    with pytest.raises(ReAuthenticationError):
        await h.sut.execute(UpdateOwnProfileRequest(email="spidey@example.com", current_password=current_password))

    h.assert_nothing_changed()


async def test_resending_the_same_email_needs_no_password() -> None:
    # Only a CHANGE of email needs re-authentication. A client that sends the
    # whole profile back, email unchanged, isn't asked for the password.
    h = _Harness()

    await h.sut.execute(UpdateOwnProfileRequest(email=_EMAIL, description="Queens, NY."))

    assert h.user.email == Email(_EMAIL)
    assert h.user.description == Description("Queens, NY.")
    assert h.transaction_manager.commit_call_count == 1


@pytest.mark.parametrize(
    "clash",
    [
        pytest.param(UsernameAlreadyExistsError(), id="username"),
        pytest.param(EmailAlreadyExistsError(), id="email"),
        pytest.param(PhoneNumberAlreadyExistsError(), id="phone_number"),
    ],
)
async def test_a_value_another_account_has_surfaces_and_nothing_is_committed(clash: BaseError) -> None:
    # The database's unique constraints catch the clash at flush; SqlaFlusher
    # turns it into the domain error (409). Nothing is committed, so the
    # request's transaction rolls back.
    h = _Harness(flush_error=clash)

    with pytest.raises(type(clash)):
        await h.sut.execute(UpdateOwnProfileRequest(username="tony-stark"))

    assert h.transaction_manager.commit_call_count == 0
