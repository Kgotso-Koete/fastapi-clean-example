from sqlalchemy import JSON, UUID, Column, DateTime, String, Table

from app.outbound.adapters.outbox_message import OutboxMessage
from app.outbound.persistence_sqla.registry import mapper_registry

event_outbox_table = Table(
    "event_outbox",
    mapper_registry.metadata,
    # Assigned by SqlaOutboxRepository.add() (uuid7, not a DB autoincrement)
    # so it can double as the Celery task_id the relay publishes under --
    # see OutboxMessage's own docstring for why.
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("event_type", String, nullable=False),
    Column("handler_type", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Nullable: NULL means still pending relay. Set once drain_outbox
    # successfully relays the row -- required even when the row is
    # retained afterward (CELERY_OUTBOX_RETAIN_AFTER_RELAY=true), since
    # "row exists" alone can no longer mean "pending" once relayed rows
    # can stick around.
    Column("processed_at", DateTime(timezone=True), nullable=True),
)


def map_event_outbox_table() -> None:
    mapper_registry.map_imperatively(
        OutboxMessage,
        event_outbox_table,
        properties={
            "id_": event_outbox_table.c.id,
            "event_type": event_outbox_table.c.event_type,
            "handler_type": event_outbox_table.c.handler_type,
            "payload": event_outbox_table.c.payload,
            "created_at": event_outbox_table.c.created_at,
            "processed_at": event_outbox_table.c.processed_at,
        },
        column_prefix="__",
    )
