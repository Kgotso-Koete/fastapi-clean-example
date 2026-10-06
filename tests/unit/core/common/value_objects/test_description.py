import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.description import Description

# Free-text prose describing an organization (and, in plan 10, a user).
# Surrounding whitespace is trimmed, and the result must be 1..MAX_LEN
# characters: an organization must always explain itself, so an empty
# Description never exists. Any printable text is allowed -- other languages,
# punctuation, emoji -- plus line breaks and tabs, since it's prose; other
# control characters (NUL, escape, DEL...) are rejected.


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("a" * Description.MIN_LEN, id="min_len"),
        pytest.param("a" * Description.MAX_LEN, id="max_len"),
    ],
)
def test_accepts_boundary_length(text: str) -> None:
    Description(text)


def test_min_length_is_1() -> None:
    assert Description.MIN_LEN == 1


def test_max_length_is_1000() -> None:
    assert Description.MAX_LEN == 1000


def test_rejects_above_max_length() -> None:
    with pytest.raises(BusinessTypeError):
        Description("a" * (Description.MAX_LEN + 1))


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="spaces_only"),
        pytest.param("\n\t\r\n", id="line_breaks_and_tabs_only"),
    ],
)
def test_rejects_blank(text: str) -> None:
    # Blank would mean "no description", which an organization may not have.
    with pytest.raises(BusinessTypeError):
        Description(text)


def test_strips_surrounding_whitespace() -> None:
    assert Description("  Earth's mightiest heroes.\n").value == "Earth's mightiest heroes."


def test_length_is_checked_after_trimming() -> None:
    padded = f"  {'a' * Description.MAX_LEN}  "

    assert Description(padded).value == "a" * Description.MAX_LEN


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Line one.\nLine two.", id="newline"),
        pytest.param("Line one.\r\nLine two.", id="windows_line_break"),
        pytest.param("Name:\tAvengers", id="inner_tab"),
        pytest.param("Héros les plus puissants de la Terre", id="non_ascii_letters"),
        pytest.param("Assemble! (Again?) -- 100% sure; ok...", id="punctuation"),
        pytest.param("Avengers 🦸", id="emoji"),
    ],
)
def test_accepts_prose(text: str) -> None:
    # Unlike OrganizationName, this is prose: kept exactly, inside the trim.
    assert Description(text).value == text


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Hidden\x00null", id="nul"),
        pytest.param("Bell\x07character", id="bell"),
        pytest.param("Escape\x1b[31mred", id="escape_sequence"),
        pytest.param("Delete\x7fcharacter", id="delete"),
    ],
)
def test_rejects_other_control_characters(text: str) -> None:
    # Control characters other than tab, newline and carriage return can
    # break storage, logs and terminals (NUL is invalid in Postgres text,
    # escape sequences can spoof terminal output), and are never prose.
    with pytest.raises(BusinessTypeError):
        Description(text)
