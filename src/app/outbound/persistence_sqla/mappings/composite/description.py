"""
The original author's nullable-composite recipe (upstream commit 5d68d52,
mappings/composite/utc_datetime.py), applied to Description, so
User.description can be a plain `Description | None` attribute
(docs/plans/10-profile-editing.md, decision 1).
"""

from app.core.common.value_objects.description import Description


def nullable_description(value: str | None) -> Description | None:
    # Given to composite() instead of the Description class, so a NULL column
    # loads as None rather than crashing in Description(None).
    if value is None:
        return None
    return Description(value)


def patch() -> None:
    # Given a function instead of the class, SQLAlchemy can't read the value
    # back out of a Description when saving; __composite_values__ tells it
    # (one entry per column). The hasattr guard makes a second call harmless,
    # since the mappings may be set up more than once in one process.
    if not hasattr(Description, "__composite_values__"):
        setattr(  # noqa: B010
            Description,
            "__composite_values__",
            lambda self: (self.value,),
        )
