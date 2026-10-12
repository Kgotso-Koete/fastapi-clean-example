"""
Initializes `__composite_values__` on VOs that are mapped via `composite(func, *cols)`
where `func` is a function (not the VO class itself).

SQLAlchemy reads values from a dataclass-VO automatically when it's passed directly to
`composite(...)`. When a function is passed instead, SQLAlchemy can't extract values on
assignment — `__composite_values__` must be patched onto the VO class. In practice this
mostly applies to nullable composites (where a function returns `VO | None`).
"""

# The original author's file (upstream commit 5d68d52), as written, patching
# Description instead of upstream's UtcDatetime
# (docs/plans/10-profile-editing.md, decision 1). Called from map_tables(), so
# whatever sets up the mappings also applies the patches.

from app.outbound.persistence_sqla.mappings.composite import description


def patch_composite() -> None:
    description.patch()
