import pytest

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.organization_name import OrganizationName

# A display name, so looser than Username -- spaces are allowed ("Midnight
# Suns") -- but still restricted to ASCII letters, digits and the separators
# " ", "-" and "_". A separator may not start or end the name, and two
# separators may never appear in a row. Surrounding whitespace is trimmed,
# and the trimmed result must be 1..MAX_LEN characters.


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("a" * OrganizationName.MIN_LEN, id="min_len"),
        pytest.param("a" * OrganizationName.MAX_LEN, id="max_len"),
    ],
)
def test_accepts_boundary_length(name: str) -> None:
    OrganizationName(name)


def test_min_length_is_1() -> None:
    assert OrganizationName.MIN_LEN == 1


def test_max_length_is_100() -> None:
    assert OrganizationName.MAX_LEN == 100


def test_rejects_above_max_length() -> None:
    with pytest.raises(BusinessTypeError):
        OrganizationName("a" * (OrganizationName.MAX_LEN + 1))


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace_only"),
        pytest.param("\t\n", id="tabs_and_newlines_only"),
    ],
)
def test_rejects_blank(name: str) -> None:
    # Whitespace-only must fail too -- it trims down to an empty name.
    with pytest.raises(BusinessTypeError):
        OrganizationName(name)


def test_strips_surrounding_whitespace() -> None:
    assert OrganizationName("  Avengers  ").value == "Avengers"


def test_length_is_checked_after_trimming() -> None:
    # MAX_LEN real characters padded with spaces is still valid -- the
    # padding is trimmed away before the length rule applies.
    padded = f"  {'a' * OrganizationName.MAX_LEN}  "

    assert OrganizationName(padded).value == "a" * OrganizationName.MAX_LEN


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Avengers", id="letters"),
        pytest.param("Fantastic 4", id="letters_digit_and_space"),
        pytest.param("X-Men", id="hyphen"),
        pytest.param("Stark_Industries", id="underscore"),
        pytest.param("Midnight Suns", id="space"),
        pytest.param("42", id="digits_only"),
    ],
)
def test_accepts_letters_digits_and_the_allowed_separators(name: str) -> None:
    assert OrganizationName(name).value == name


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("S.H.I.E.L.D.", id="dot"),
        pytest.param("Avengers!", id="exclamation"),
        pytest.param("X@Men", id="at_sign"),
        pytest.param("Team#1", id="hash"),
        pytest.param("Stark/Industries", id="slash"),
        pytest.param("Guardians, Inc", id="comma"),
        pytest.param("Midnight\tSuns", id="inner_tab"),
        pytest.param("Société", id="non_ascii_letter"),
        pytest.param("Rocket 🚀", id="emoji"),
    ],
)
def test_rejects_any_other_character(name: str) -> None:
    # Only " " counts as the space separator -- an inner tab is rejected,
    # even though surrounding tabs are simply trimmed away.
    with pytest.raises(BusinessTypeError):
        OrganizationName(name)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("-Avengers", id="leading_hyphen"),
        pytest.param("_Avengers", id="leading_underscore"),
        pytest.param("Avengers-", id="trailing_hyphen"),
        pytest.param("Avengers_", id="trailing_underscore"),
    ],
)
def test_rejects_a_separator_at_the_start_or_end(name: str) -> None:
    # A leading/trailing SPACE never reaches this rule -- it's trimmed away
    # first (see test_strips_surrounding_whitespace) -- so only "-" and "_"
    # can actually end up at either edge.
    with pytest.raises(BusinessTypeError):
        OrganizationName(name)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("X--Men", id="double_hyphen"),
        pytest.param("Stark__Industries", id="double_underscore"),
        pytest.param("Midnight  Suns", id="double_space"),
        pytest.param("X- Men", id="hyphen_then_space"),
        pytest.param("Stark_-Industries", id="underscore_then_hyphen"),
    ],
)
def test_rejects_consecutive_separators(name: str) -> None:
    # Any two separators in a row, same or mixed -- mirrors Username's
    # "no consecutive special characters" rule.
    with pytest.raises(BusinessTypeError):
        OrganizationName(name)


def test_accepts_single_separators_between_words() -> None:
    # The positive counterpart: one separator between each pair of words,
    # of any of the three kinds, is fine.
    name = "Stark Industries-West_Coast"

    assert OrganizationName(name).value == name
