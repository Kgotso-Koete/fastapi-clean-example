"""
Sentinel for "value was not provided", as opposed to `None` ("provided as empty").
Single-member `Enum`: type checkers narrow `is` only for enum members, `None` and literals.
"""

# Ported unchanged from the original author's "Autumn 2026 Updates & Fixes"
# (docs/plans/15-upstream-autumn-2026.md, Step 2); only these comments are
# added.
#
# What a sentinel is: a special, one-of-a-kind marker value that stands for a
# situation rather than for data. Code recognises it by identity (`is`), so it
# can never be mistaken for a real value a user sent. Python's own `None` is
# the best-known sentinel ("no value"); OMITTED below is a second one, for a
# situation `None` can't express.
#
# What this one is for: a PATCH request needs three states per field, and
# None alone can only express two:
# - OMITTED: the field was left out of the request, so keep the stored value;
# - None: the field was sent as null, so clear it;
# - a value: the field was sent, so validate and store it.
# The web layer turns pydantic's own "not sent" marker into OMITTED
# (app.inbound.missing.omit_if_missing), so core never depends on pydantic.

from collections.abc import Callable
from enum import Enum
from typing import Final, overload


class Omitted(Enum):
    OMITTED = "OMITTED"


# The one value to compare against: `if value is OMITTED: ...`.
OMITTED: Final = Omitted.OMITTED


# The two overloads tell mypy that None can only come out if None could go
# in, so a field that can't be cleared (typed `T | Omitted`) never gains a
# `None` it would then have to handle.
@overload
def apply_when_present[T, R](func: Callable[[T], R], value: T | Omitted) -> R | Omitted: ...
@overload
def apply_when_present[T, R](func: Callable[[T], R], value: T | Omitted | None) -> R | Omitted | None: ...
def apply_when_present[T, R](func: Callable[[T], R], value: T | Omitted | None) -> R | Omitted | None:
    # Runs `func` (typically a value object's constructor) only on a real
    # value; "left out" and "cleared" pass through untouched.
    if value is OMITTED:
        return OMITTED
    if value is None:
        return None
    return func(value)
