from datetime import UTC, datetime
from uuid import uuid4

from app.core.common.entities.types_ import UserId, UserPasswordHash, UserRole
from app.core.common.entities.user import User
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime

_DEFAULT_NOW = UtcDatetime(datetime(2026, 1, 1, tzinfo=UTC))


def _create_user_with_description(description: str) -> User:
    # A small, self-contained factory, since only this file needs it --
    # mirrors test_organization.py's own _create_organization helper.
    return User(
        id_=UserId(uuid4()),
        username=Username("tony-stark"),
        email=Email("tony.stark@starkindustries.com"),
        phone_number=PhoneNumber("27821000012"),
        password_hash=UserPasswordHash(b"not-a-real-hash"),
        role=UserRole.USER,
        is_active=True,
        created_at=_DEFAULT_NOW,
        updated_at=_DEFAULT_NOW,
        description=Description(description),
    )


def test_a_user_built_without_a_description_has_none() -> None:
    # Built inline, with no description argument, exactly as every existing
    # caller (UserService.create_user, the test factories, the seed script)
    # builds a User. The argument's None default is what keeps them all
    # working unchanged (docs/plans/10-profile-editing.md, decision 1).
    sut = User(
        id_=UserId(uuid4()),
        username=Username("peter-parker"),
        email=Email("peter.parker@dailybugle.com"),
        phone_number=PhoneNumber("27821000011"),
        password_hash=UserPasswordHash(b"not-a-real-hash"),
        role=UserRole.USER,
        is_active=True,
        created_at=_DEFAULT_NOW,
        updated_at=_DEFAULT_NOW,
    )

    assert sut.description is None


def test_a_user_keeps_the_description_it_was_built_with() -> None:
    # The entity holds the validated value object, not a raw str -- the same
    # way Organization holds its Description.
    sut = _create_user_with_description("Genius, billionaire, philanthropist.")

    assert sut.description == Description("Genius, billionaire, philanthropist.")


def test_setting_a_description_replaces_it() -> None:
    sut = _create_user_with_description("Genius, billionaire, philanthropist.")

    sut.description = Description("I am Iron Man.")

    assert sut.description == Description("I am Iron Man.")


def test_clearing_the_description_sets_it_to_none() -> None:
    # Decision 3: in a PATCH, {"description": null} clears it. At the entity
    # level that is simply assigning None.
    sut = _create_user_with_description("Genius, billionaire, philanthropist.")

    sut.description = None

    assert sut.description is None
