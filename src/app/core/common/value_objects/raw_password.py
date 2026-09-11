from dataclasses import dataclass, field
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class RawPassword(ValueObject):
    MIN_LEN: ClassVar[int] = 12
    MAX_LEN: ClassVar[int] = 128
    SPECIAL_CHARS: ClassVar[str] = "!@#$%^&*()_+-=[]{}|;:,.<>?"

    value: bytes = field(init=False, repr=False)

    def __init__(self, value: str) -> None:
        self._validate(value)
        object.__setattr__(self, "value", value.encode())

    @classmethod
    def _validate(cls, value: str) -> None:
        if len(value) < cls.MIN_LEN:
            raise BusinessTypeError(f"Password must be at least {cls.MIN_LEN} characters long.")
        if len(value) > cls.MAX_LEN:
            raise BusinessTypeError(f"Password must be at most {cls.MAX_LEN} characters long.")
        if not any(c.isalpha() for c in value):
            raise BusinessTypeError("Password must contain at least one letter.")
        if not any(c.isdigit() for c in value):
            raise BusinessTypeError("Password must contain at least one digit.")
        if not any(c in cls.SPECIAL_CHARS for c in value):
            raise BusinessTypeError(f"Password must contain at least one special character ({cls.SPECIAL_CHARS}).")
