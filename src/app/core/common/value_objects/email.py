import re
from dataclasses import dataclass
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class Email(ValueObject):
    """
    Email address, stripped of surrounding whitespace and lowercased
    for consistent storage and comparison.
    """

    MAX_LEN: ClassVar[int] = 254  # RFC 5321 total length limit

    PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
        r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
    )

    value: str

    def __init__(self, value: str) -> None:
        normalized = self._normalize(value)
        self._validate(normalized)
        object.__setattr__(self, "value", normalized)

    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()

    @classmethod
    def _validate(cls, value: str) -> None:
        if not value or len(value) > cls.MAX_LEN:
            raise BusinessTypeError(f"{cls.__name__} must be between 1 and {cls.MAX_LEN} characters.")
        if not cls.PATTERN.fullmatch(value):
            raise BusinessTypeError(f"{cls.__name__} must be a valid email address, e.g. 'name@example.com'.")
