"""
Gives every entity SQLAlchemy loads from the database the same starting state
its constructor would have given it.

### The problem:
`Entity.__init__` (core/common/entities/base.py) creates the entity's empty
`_events` list, which `record_event()`/`collect_events()` rely on. But when
SQLAlchemy builds an entity from a database row, it deliberately does NOT call
`__init__` -- so a LOADED entity has no `_events` at all, and recording a domain
event on it raises AttributeError. Freshly constructed entities never hit
this; an entity loaded, changed, and then asked to record an event does (the
first case: InviteOrganizationMember renewing an expired invitation it read
back from Postgres, found by docs/plans/9-organizations.md's human checks).

### The solution:
SQLAlchemy's `load` instance event runs once for every object it builds from
a row -- its documented hook for exactly this, re-establishing state that
`__init__` would normally set up. Listening on the unmapped `Entity` base
class with `propagate=True` covers every mapped subclass (User, ApiKey,
Organization, OrganizationMembership, and any added later), so no per-table
wiring is needed. The domain layer stays unaware SQLAlchemy exists.
"""

from typing import Any

from sqlalchemy import event

from app.core.common.entities.base import Entity


def _give_loaded_entity_an_empty_event_list(entity: Entity[Any], _context: Any) -> None:
    # Mirrors the one line of Entity.__init__ that loading skips -- including
    # object.__setattr__, the same way __init__ sets it. `load` fires only when
    # SQLAlchemy first builds the object, never on a later refresh, so an
    # already-recorded event is never wiped out by this.
    object.__setattr__(entity, "_events", [])


def listen_for_entity_loads() -> None:
    # Must be registered BEFORE the imperative mappings are made (see
    # map_tables() in mappings/all.py), so every entity class picks it up as
    # soon as it is mapped.
    event.listen(Entity, "load", _give_loaded_entity_an_empty_event_list, propagate=True)
