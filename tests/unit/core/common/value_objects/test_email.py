import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.email import Email


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("user@example.com", "user@example.com"),
        ("USER@EXAMPLE.COM", "user@example.com"),
        ("  user@example.com  ", "user@example.com"),
        ("first.last@example.co.za", "first.last@example.co.za"),
        ("user+tag@example.com", "user+tag@example.com"),
        ("user_name@sub.example.com", "user_name@sub.example.com"),
    ],
)
def test_accepts_and_normalizes_valid_emails(raw: str, expected: str) -> None:
    assert Email(raw).value == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "no-at-sign.com",
        "@example.com",
        "user@",
        "user@@example.com",
        "user@example",
        "user@.com",
        "user@example..com",
        "user name@example.com",
    ],
)
def test_rejects_invalid_emails(raw: str) -> None:
    with pytest.raises(BusinessTypeError):
        Email(raw)


def test_rejects_too_long_email() -> None:
    local_part = "a" * Email.MAX_LEN
    with pytest.raises(BusinessTypeError):
        Email(f"{local_part}@example.com")
