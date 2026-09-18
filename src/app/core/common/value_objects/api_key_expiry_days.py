from dataclasses import dataclass
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class ApiKeyExpiryDays(ValueObject):
    """
    Caller-chosen expiry for a newly issued API key, in days.
    Bounded so a key can neither expire immediately nor be granted
    an effectively-unlimited lifetime.
    """

    MIN_DAYS: ClassVar[int] = 1
    MAX_DAYS: ClassVar[int] = 365

    value: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (self.MIN_DAYS <= self.value <= self.MAX_DAYS):
            raise BusinessTypeError(f"Expiry must be between {self.MIN_DAYS} and {self.MAX_DAYS} days.")
