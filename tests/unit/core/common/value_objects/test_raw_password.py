import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.raw_password import RawPassword


def _complex_password(length: int) -> str:
    # Guarantees a letter, a digit, and a special char; pads with letters to hit an exact length.
    prefix = "Aa1!"
    return prefix + "a" * (length - len(prefix))


def test_accepts_boundary_length() -> None:
    password = _complex_password(RawPassword.MIN_LEN)

    RawPassword(password)


def test_rejects_out_of_bounds_length() -> None:
    password = "a" * (RawPassword.MIN_LEN - 1)

    with pytest.raises(BusinessTypeError):
        RawPassword(password)


def test_minimum_length_is_12() -> None:
    assert RawPassword.MIN_LEN == 12


def test_maximum_length_is_128() -> None:
    assert RawPassword.MAX_LEN == 128


def test_accepts_max_boundary_length() -> None:
    password = _complex_password(RawPassword.MAX_LEN)

    RawPassword(password)


def test_rejects_above_max_length() -> None:
    password = "a" * (RawPassword.MAX_LEN + 1)

    with pytest.raises(BusinessTypeError):
        RawPassword(password)


def test_rejects_password_without_a_letter() -> None:
    with pytest.raises(BusinessTypeError):
        RawPassword("123456789012!")


def test_rejects_password_without_a_digit() -> None:
    with pytest.raises(BusinessTypeError):
        RawPassword("abcdefghijkl!")


def test_rejects_password_without_a_special_character() -> None:
    with pytest.raises(BusinessTypeError):
        RawPassword("abcdefgh1234")


def test_accepts_password_with_letter_digit_and_special_character() -> None:
    RawPassword(_complex_password(RawPassword.MIN_LEN))


def test_accepts_every_allowed_special_character() -> None:
    for char in RawPassword.SPECIAL_CHARS:
        RawPassword(f"abcdefg1234{char}")
