import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.phone_number import PhoneNumber


@pytest.mark.parametrize(
    "raw",
    [
        "+27 83 123-4567",
        "083 (123) 4567",
        "2783_123[4567]",
        "0831234567",
        "27831234567",
        "+27831234567",
    ],
)
def test_normalizes_valid_numbers_to_country_code_format(raw: str) -> None:
    assert PhoneNumber(raw).value == "27831234567"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "123",
        "12345678901234",
        "12831234567",  # 11 digits but wrong country code
        "083123456",  # local format, one digit too short
        "08312345678",  # local format, one digit too long
        "+44 20 7946 0958",  # non-SA number
    ],
)
def test_rejects_invalid_numbers(raw: str) -> None:
    with pytest.raises(BusinessTypeError):
        PhoneNumber(raw)
