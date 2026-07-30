import re
from dataclasses import dataclass
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class PhoneNumber(ValueObject):
    """
    South African phone number.
    Accepts common human-entered formats (+27, leading 0, spaces, dashes,
    brackets, underscores, etc.) and normalizes them to a country-code-prefixed,
    digits-only string, e.g. "27831234567".
    """

    MAX_LEN: ClassVar[int] = 11  # e.g 27831234567
    COUNTRY_CODE: ClassVar[str] = "27"
    LOCAL_LEN: ClassVar[int] = 10  # e.g. 0831234567 (leading 0 + 9 digits)
    NORMALIZED_LEN: ClassVar[int] = 11  # e.g. 27831234567 (country code + 9 digits)

    PATTERN_NON_DIGITS: ClassVar[re.Pattern[str]] = re.compile(r"\D+")

    value: str

    def __init__(self, value: str) -> None:
        normalized = self._normalize(value)
        object.__setattr__(self, "value", normalized)

    @classmethod
    def _normalize(cls, value: str) -> str:
        digits = cls.PATTERN_NON_DIGITS.sub("", value)

        if digits.startswith(cls.COUNTRY_CODE) and len(digits) == cls.NORMALIZED_LEN:
            candidate = digits
        elif digits.startswith("0") and len(digits) == cls.LOCAL_LEN:
            candidate = cls.COUNTRY_CODE + digits[1:]
        else:
            raise BusinessTypeError(
                f"{cls.__name__} must be a valid South African number, e.g. '0831234567' or '+27831234567'."
            )

        cls._validate(candidate)
        return candidate

    @classmethod
    def _validate(cls, candidate: str) -> None:
        if len(candidate) != cls.NORMALIZED_LEN or not candidate.isdigit():
            raise BusinessTypeError(f"Normalized {cls.__name__} must be exactly {cls.NORMALIZED_LEN} digits.")
        if not candidate.startswith(cls.COUNTRY_CODE):
            raise BusinessTypeError(f"{cls.__name__} must use the South African country code '{cls.COUNTRY_CODE}'.")
