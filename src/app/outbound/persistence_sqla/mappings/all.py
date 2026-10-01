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

from app.outbound.persistence_sqla.entity_load_events import listen_for_entity_loads
from app.outbound.persistence_sqla.mappings.api_key import map_api_keys_table
from app.outbound.persistence_sqla.mappings.auth_session import map_auth_sessions_table
from app.outbound.persistence_sqla.mappings.organization import map_organizations_table
from app.outbound.persistence_sqla.mappings.organization_membership import map_organization_memberships_table
from app.outbound.persistence_sqla.mappings.outbox_message import map_event_outbox_table
from app.outbound.persistence_sqla.mappings.user import map_users_table
from app.outbound.persistence_sqla.registry import mapper_registry


def map_tables() -> None:
    if mapper_registry.mappers:
        return
    # First, so every mapped entity gets its _events list back on load --
    # see entity_load_events.py.
    listen_for_entity_loads()
    map_users_table()
    map_auth_sessions_table()
    map_event_outbox_table()
    map_api_keys_table()
    map_organizations_table()
    map_organization_memberships_table()
