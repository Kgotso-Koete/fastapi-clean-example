from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(eq=False, kw_only=True)
class OutboxMessage:
    """
    A durable, transactional record of a "background"-mode handler still
    waiting to be published to Celery (or already relayed, if retained --
    see CELERY_OUTBOX_RETAIN_AFTER_RELAY). HybridEventDispatcher.stage()
    writes one of these in the same DB transaction as the domain change
    that raised the event; app.main.worker's outbox drain loop later
    relays it to Celery, marks it processed, and deletes it too only if
    retention is disabled.

    id_ is a UUID assigned by SqlaOutboxRepository.add() (not a DB
    autoincrement) precisely so it can double as the Celery task_id the
    relay publishes under -- see outbox_drain_loop._drain_outbox. That
    makes this one id traceable across all three places a relayed event
    shows up:
    the event_outbox row itself, the Celery task, and its Redis result
    key. A plain autoincrement int would work as a task_id too, but risks
    colliding with an unrelated task/id scheme elsewhere down the line --
    a UUID rules that out entirely.

    processed_at is nullable and required regardless of the retention
    setting: a retained-after-relay row still has to be distinguishable
    from a pending one, since "row exists" no longer means "pending" once
    relayed rows can stick around.

    Plain outbound record, not a core domain entity -- mirrors how
    AuthSession (app.outbound.auth_ctx.model) is a plain infrastructure
    class rather than a rich Entity subclass.
    """

    id_: UUID | None = None
    event_type: str
    handler_type: str
    payload: dict[str, Any]
    created_at: datetime
    processed_at: datetime | None = None
