from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import compat as uuid_utils

from app.core.commands.ports.outbox_repository import OutboxRepository
from app.outbound.adapters.outbox_message import OutboxMessage
from app.outbound.exceptions import StorageError
from app.outbound.persistence_sqla.mappings.outbox_message import event_outbox_table

# Caps how many rows one outbox_drain_loop tick will relay -- keeps a
# single tick from pulling an unbounded backlog into memory at once if the
# worker/broker was ever down for a while.
_DRAIN_BATCH_SIZE = 100


class SqlaOutboxRepository(OutboxRepository):
    """
    Fulfills the core OutboxRepository port (add() only) for the web
    process's pre-commit stage() write. Also exposes
    get_pending()/mark_processed()/delete()/commit(), which
    app.main.worker.outbox_drain_loop calls directly by this concrete
    class -- they're pure worker-side housekeeping with no core
    business-logic meaning, so they're deliberately not part of the
    OutboxRepository Protocol itself. See docs/plans/4-transactional-outbox.md.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, *, event_type: str, handler_type: str, payload: dict[str, Any]) -> None:
        try:
            self._session.add(
                OutboxMessage(
                    # uuid7 (time-sortable), matching the id scheme
                    # id_factory.create_user_id() already uses for User --
                    # this id also becomes the Celery task_id the relay
                    # publishes under (see OutboxMessage's docstring), so
                    # it's generated here rather than left to a DB
                    # autoincrement default.
                    id_=uuid_utils.uuid7(),
                    event_type=event_type,
                    handler_type=handler_type,
                    payload=payload,
                    created_at=datetime.now(UTC),
                )
            )
        except SQLAlchemyError as e:
            raise StorageError from e

    async def get_pending(self) -> list[OutboxMessage]:
        """
        Oldest-first, capped at _DRAIN_BATCH_SIZE. processed_at IS NULL is
        what distinguishes a still-pending row from an already-relayed one
        that's being retained (see CELERY_OUTBOX_RETAIN_AFTER_RELAY) --
        "row exists" alone can no longer mean "pending" once relayed rows
        can stick around.

        with_for_update(skip_locked=True): more than one process can call
        this concurrently -- Celery's prefork pool starts
        CELERY_WORKER_CONCURRENCY separate child processes, each running
        its own outbox_drain_loop, and a production deployment may run
        several `worker` replicas too. Without row locking, two calls
        racing each other could both return the same still-unprocessed
        row, and both relay it. Locking each row this SELECT returns, and
        skipping any row a concurrent call already has locked, makes
        every call's batch disjoint from every other's instead. The lock
        is held until commit() runs -- see its own docstring for why that
        must happen once, after the whole batch, not per row.
        """
        stmt = (
            select(OutboxMessage)
            .where(event_outbox_table.c.processed_at.is_(None))
            .order_by(event_outbox_table.c.created_at.asc())
            .limit(_DRAIN_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return list(result.scalars().all())

    async def mark_processed(self, message: OutboxMessage) -> None:
        """
        Always called right after a successful relay, regardless of the
        retention setting. Just marks the in-memory object dirty -- does
        not commit, see commit()'s docstring for why.
        """
        message.processed_at = datetime.now(UTC)

    async def delete(self, message: OutboxMessage) -> None:
        """
        Called in addition to mark_processed(), only when
        CELERY_OUTBOX_RETAIN_AFTER_RELAY is False. Does not commit -- see
        commit()'s docstring for why.
        """
        try:
            await self._session.delete(message)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def commit(self) -> None:
        """
        Commits every mark_processed()/delete() call made against the
        batch get_pending() most recently returned, releasing that
        batch's FOR UPDATE locks. Called once, after the whole batch has
        been relayed and marked/deleted -- not per row. Committing
        earlier, partway through the batch, would release the lock on
        this same batch's own not-yet-processed rows immediately, which
        would let a concurrent call's get_pending() see them as
        unprocessed and unlocked again and relay them too, reopening the
        exact race get_pending()'s row locking exists to close.
        """
        try:
            await self._session.commit()
        except SQLAlchemyError as e:
            raise StorageError from e
