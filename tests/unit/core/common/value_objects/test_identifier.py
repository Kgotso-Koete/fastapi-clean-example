import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.identifier import resolve_username_or_email
from app.core.common.value_objects.username import Username


def test_resolves_a_valid_email_string_to_an_email() -> None:
    resolved = resolve_username_or_email("user@example.com")

    assert isinstance(resolved, Email)
    assert resolved.value == "user@example.com"


def test_resolves_a_valid_username_string_to_a_username() -> None:
    resolved = resolve_username_or_email("username")

    assert isinstance(resolved, Username)
    assert resolved.value == "username"


def test_raises_when_string_is_neither_a_valid_email_nor_a_valid_username() -> None:
    # Too short to be a Username and missing "@" to be an Email, so both
    # constructions fail and the Username error is the one that propagates.
    with pytest.raises(BusinessTypeError):
        resolve_username_or_email("")
