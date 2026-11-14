"""
Ensures imperative SQLAlchemy mappings are initialized at application startup.

### Purpose:
In Clean Architecture, domain entities remain agnostic of database
mappings. To integrate with SQLAlchemy, mappings must be explicitly
triggered to link ORM attributes to domain classes. Without this setup,
attempts to interact with unmapped entities in database operations
will lead to runtime errors.

### Solution:
This module provides a single entry point to initialize the mapping
of domain entities to database tables. By calling the `map_tables` function,
ORM attributes are linked to domain classes without altering domain code
or introducing infrastructure concerns.

### Usage:
Call the `map_tables` function in the application factory to initialize
mappings at startup. Additionally, it is necessary to call this function
in `env.py` for Alembic migrations to ensure all models are available
during database migrations.
"""

from collections.abc import Callable, Sequence

from app.base.outbound.persistence_sqla.entity_load_events import listen_for_entity_loads
from app.base.outbound.persistence_sqla.mappings.api_key import map_api_keys_table
from app.base.outbound.persistence_sqla.mappings.auth_session import map_auth_sessions_table
from app.base.outbound.persistence_sqla.mappings.composite.registry import patch_composite
from app.base.outbound.persistence_sqla.mappings.outbox_message import map_event_outbox_table
from app.base.outbound.persistence_sqla.mappings.user import map_users_table
from app.base.outbound.persistence_sqla.registry import mapper_registry


def map_tables(*, module_mappings: Sequence[Callable[[], None]]) -> None:
    # module_mappings: the registered units' table-mapping functions, in
    # registration order (docs/plans/16-modular-monolith.md, Step 4d). The caller
    # collects them from the registry in src/app/base/main/modules.py, which this
    # file may not import (base's outbound sits below the modules). The type is
    # spelled out rather than imported as the registry's TableMapping alias, for
    # the same reason. Required, with no default, so every caller says which
    # units' tables it maps. Only the first call maps anything (the guard below),
    # and every entrypoint passes the same list.
    if mapper_registry.mappers:
        return
    # First, so every mapped entity gets its _events list back on load --
    # see entity_load_events.py.
    listen_for_entity_loads()
    # Before any mapping: composite(nullable_description, ...) needs
    # Description patched to save -- see mappings/composite/registry.py.
    patch_composite()
    map_users_table()
    map_auth_sessions_table()
    map_event_outbox_table()
    map_api_keys_table()
    # Then each registered unit's tables, after base's, which they may reference.
    for map_unit_tables in module_mappings:
        map_unit_tables()
