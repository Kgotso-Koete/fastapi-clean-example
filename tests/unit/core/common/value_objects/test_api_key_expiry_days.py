import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.api_key_expiry_days import ApiKeyExpiryDays


def test_accepts_minimum_boundary() -> None:
    ApiKeyExpiryDays(ApiKeyExpiryDays.MIN_DAYS)


def test_accepts_maximum_boundary() -> None:
    ApiKeyExpiryDays(ApiKeyExpiryDays.MAX_DAYS)


def test_rejects_below_minimum() -> None:
    with pytest.raises(BusinessTypeError):
        ApiKeyExpiryDays(ApiKeyExpiryDays.MIN_DAYS - 1)


def test_rejects_above_maximum() -> None:
    with pytest.raises(BusinessTypeError):
        ApiKeyExpiryDays(ApiKeyExpiryDays.MAX_DAYS + 1)


def test_minimum_is_one_day() -> None:
    assert ApiKeyExpiryDays.MIN_DAYS == 1


def test_maximum_is_365_days() -> None:
    assert ApiKeyExpiryDays.MAX_DAYS == 365
