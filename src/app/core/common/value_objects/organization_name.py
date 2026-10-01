import re
from dataclasses import dataclass
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class OrganizationName(ValueObject):
    """
    An organization's display name, stripped of surrounding whitespace.

    Looser than Username in one way only -- a space is allowed as a
    separator ("Midnight Suns"), since this is shown to people rather than
    used as an identifier. Otherwise the same shape of rules as Username:
    ASCII letters, digits and single separators (" ", "-", "_") between
    them, never at either edge and never two in a row.
    """

    MIN_LEN: ClassVar[int] = 1
    MAX_LEN: ClassVar[int] = 100

    # Mirrors Username's PATTERN_* rules, with " " added to the separators.
    # 1) allowed alphabet only -- ASCII letters/digits, space, hyphen, underscore
    PATTERN_ALLOWED_CHARS: ClassVar[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9 _-]+$")
    # 2) start / end must be alnum
    PATTERN_START: ClassVar[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9]")
    PATTERN_END: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]$")
    # 3) no consecutive separators, same or mixed
    PATTERN_CONSECUTIVE_SEPARATORS: ClassVar[re.Pattern[str]] = re.compile(r"[ _-]{2,}")

    value: str

    def __init__(self, value: str) -> None:
        # Same normalize-then-validate shape as Email: trim first, so padding
        # never counts toward the length and whitespace-only names are blank.
        normalized = self._normalize(value)
        self._validate(normalized)
        object.__setattr__(self, "value", normalized)

    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip()

    @classmethod
    def _validate(cls, value: str) -> None:
        if len(value) < cls.MIN_LEN or len(value) > cls.MAX_LEN:
            raise BusinessTypeError(f"{cls.__name__} must be between {cls.MIN_LEN} and {cls.MAX_LEN} characters.")
        if not cls.PATTERN_ALLOWED_CHARS.fullmatch(value):
            raise BusinessTypeError(
                f"{cls.__name__} can only contain letters (A-Z, a-z), digits (0-9), "
                "spaces, hyphens (-), and underscores (_)."
            )
        if not cls.PATTERN_START.match(value):
            raise BusinessTypeError(f"{cls.__name__} must start with a letter (A-Z, a-z) or a digit (0-9).")
        if not cls.PATTERN_END.search(value):
            raise BusinessTypeError(f"{cls.__name__} must end with a letter (A-Z, a-z) or a digit (0-9).")
        if cls.PATTERN_CONSECUTIVE_SEPARATORS.search(value):
            raise BusinessTypeError(f"{cls.__name__} cannot contain consecutive separators like '--', '__', or '  '.")
