import unicodedata
from dataclasses import dataclass
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class Description(ValueObject):
    """
    Free-text prose describing an organization (and, in plan 10, a user),
    stripped of surrounding whitespace.

    Unlike OrganizationName this is prose, not a label: any printable text is
    allowed -- other languages, punctuation, emoji -- plus tab, newline and
    carriage return (browsers send textarea line breaks as \\r\\n). Every other
    control character is rejected: NUL can't be stored in Postgres text, and
    escape sequences could spoof terminal output wherever this gets logged.

    Never empty: an organization must always explain itself, so blank input
    is rejected rather than stored.
    """

    MIN_LEN: ClassVar[int] = 1
    MAX_LEN: ClassVar[int] = 1000

    # The only control characters prose legitimately contains.
    ALLOWED_CONTROL_CHARS: ClassVar[frozenset[str]] = frozenset({"\t", "\n", "\r"})

    value: str

    def __init__(self, value: str) -> None:
        # Same normalize-then-validate shape as OrganizationName: trim first,
        # so padding never counts toward the length, and whitespace-only
        # input is blank.
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
        # Unicode category "Cc" is exactly the control characters (NUL, bell,
        # escape, DEL...); printable text in any script is never in it.
        if any(unicodedata.category(char) == "Cc" and char not in cls.ALLOWED_CONTROL_CHARS for char in value):
            raise BusinessTypeError(
                f"{cls.__name__} cannot contain control characters other than tabs and line breaks."
            )
