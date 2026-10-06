from sqlalchemy import UUID, Column, DateTime, ForeignKey, String, Table
from sqlalchemy.orm import composite

from app.core.common.entities.organization import Organization
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.persistence_sqla.registry import mapper_registry

organizations_table = Table(
    "organizations",
    mapper_registry.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    # Mandatory, like name: every organization explains itself. Length and
    # allowed characters are Description's rules, not the column's.
    Column("description", String, nullable=False),
    # No ondelete: deleting a user must not silently take their
    # organization (and every other member's access to it) with them.
    Column("created_by_user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def map_organizations_table() -> None:
    mapper_registry.map_imperatively(
        Organization,
        organizations_table,
        properties={
            "id_": organizations_table.c.id,
            # Wrapped in the value object on load and unwrapped on write, the
            # same way users.username maps to Username.
            "name": composite(OrganizationName, organizations_table.c.name),
            # Non-nullable, so composite() is safe -- the same as name.
            "description": composite(Description, organizations_table.c.description),
            "created_by_user_id": organizations_table.c.created_by_user_id,
            # Non-nullable, so composite() is safe here -- same as
            # ApiKey.created_at.
            "_created_at": composite(UtcDatetime, organizations_table.c.created_at),
        },
        column_prefix="__",
    )
