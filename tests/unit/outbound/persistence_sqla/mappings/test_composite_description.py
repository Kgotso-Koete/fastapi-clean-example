from app.core.common.value_objects.description import Description
from app.outbound.persistence_sqla.mappings.composite.description import nullable_description, patch

# The original author's nullable-composite recipe, applied to Description
# (docs/plans/10-profile-editing.md, Step 2). composite() is given
# nullable_description instead of the Description class, so loading a NULL
# column gives None instead of crashing; and because SQLAlchemy can't read
# the value back out of a Description when it was given a function,
# patch() teaches it how, via __composite_values__. Both halves are plain
# Python, so they're tested here directly, with no database. That they're
# wired to the real users table is proven by
# tests/integration/with_infra/users/test_user_description_persistence.py.


def test_a_null_column_loads_as_none() -> None:
    # The case plain composite(Description, ...) can't handle: it would call
    # Description(None) and crash (docs/plans/8-public-api-key-auth.md, Step 3).
    assert nullable_description(None) is None


def test_stored_text_loads_as_a_description() -> None:
    assert nullable_description("I am Iron Man.") == Description("I am Iron Man.")


def test_after_patching_a_description_gives_sqlalchemy_its_column_value() -> None:
    # What SQLAlchemy calls on save to get the column's value back out of the
    # value object: a tuple with one entry per column, here the one text column.
    patch()

    assert Description("I am Iron Man.").__composite_values__() == ("I am Iron Man.",)  # type: ignore[attr-defined]


def test_patching_twice_is_harmless() -> None:
    # The mappings may be set up more than once in one process (each test app
    # does it), so patch() must not fail or change anything on a second run.
    patch()
    patch()

    assert Description("I am Iron Man.").__composite_values__() == ("I am Iron Man.",)  # type: ignore[attr-defined]
