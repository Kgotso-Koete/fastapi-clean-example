from sqlalchemy import UUID, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import composite

from app.core.common.entities.api_key import ApiKey
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.persistence_sqla.registry import mapper_registry

api_keys_table = Table(
    "api_keys",
    mapper_registry.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    # Unique + indexed -- this is the O(1) lookup ApiKeyIdentityProvider's
    # get_by_key_hash() depends on. See the plan's "key-hashing decision".
    Column("key_hash", String, nullable=False, unique=True, index=True),
    # Non-secret, display-only -- see ApiKey.key_prefix's own docstring.
    Column("key_prefix", String, nullable=False),
    Column("label", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    # Usage-analytics footprint -- see ApiKey.record_use()'s docstring and
    # the plan's "Usage analytics" section.
    Column("use_count", Integer, nullable=False, server_default="0"),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
)


def map_api_keys_table() -> None:
    mapper_registry.map_imperatively(
        ApiKey,
        api_keys_table,
        properties={
            "id_": api_keys_table.c.id,
            "user_id": api_keys_table.c.user_id,
            "key_hash": api_keys_table.c.key_hash,
            "key_prefix": api_keys_table.c.key_prefix,
            "label": api_keys_table.c.label,
            "_created_at": composite(UtcDatetime, api_keys_table.c.created_at),
            "expires_at": composite(UtcDatetime, api_keys_table.c.expires_at),
            # Plain columns, NOT composite(UtcDatetime, ...) -- these two are
            # nullable, and ApiKey's own revoked_at/last_used_at properties
            # already do the UtcDatetime wrap/unwrap and the None-check in
            # plain Python. See those properties' docstrings for why
            # composite() specifically can't be made to work cleanly here.
            "_revoked_at": api_keys_table.c.revoked_at,
            "use_count": api_keys_table.c.use_count,
            "_last_used_at": api_keys_table.c.last_used_at,
        },
        column_prefix="__",
    )
