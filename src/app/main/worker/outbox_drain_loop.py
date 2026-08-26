import asyncio
import logging
from concurrent.futures import Future

from celery import Celery

from app.main.config.loader import load_celery_settings
from app.main.worker.celery_app import celery_app
from app.main.worker.container import get_worker_container
from app.main.worker.loop_runtime import spawn
from app.outbound.adapters.hybrid_event_dispatcher import DISPATCH_HANDLER_TASK_NAME
from app.outbound.adapters.sqla_outbox_repository import SqlaOutboxRepository

logger = logging.getLogger(__name__)

# Set by start() and cancelled by stop() (called from celery_app's
# worker_process_init/worker_process_shutdown hooks) -- module-level like
# container.py's own `_container`, since there's exactly one drain loop
# per worker *process*.
_drain_future: Future[None] | None = None


def start() -> None:
    """
    Spawns the drain loop on this process's persistent event loop
    (app.main.worker.loop_runtime.start_loop must already have run) and
    keeps a handle to it so stop() can cancel it later. Idempotent: does
    nothing if a loop is already running.
    """
    global _drain_future
    if _drain_future is not None:
        return
    _drain_future = spawn(_run_forever())


def stop() -> None:
    """Cancels the spawned loop, if one is running. Safe to call even if start() was never called."""
    global _drain_future
    if _drain_future is not None:
        _drain_future.cancel()
        _drain_future = None


async def _run_forever() -> None:
    """
    Ticks every CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS and drains whatever's
    pending, for as long as this worker process lives. Deliberately a
    plain coroutine on this process's own event loop rather than a Celery
    Beat task -- see docs/plans/4-transactional-outbox.md's "Why not a
    Celery Beat task" section: a Celery task, even with
    ignore_result=True, still publishes through the broker and shows up
    in Flower's live event stream on every tick whether or not there was
    anything to drain. Running the poll this way instead means the ONLY
    Celery tasks that ever exist are real, one-per-outbox-row
    dispatch_handler tasks -- Postgres, Celery/Flower, and Redis all stay
    a 1:1 mirror of each other, not a heartbeat log.

    A tick that raises is logged and swallowed rather than left to kill
    the loop -- a single bad tick (e.g. a transient DB blip) shouldn't
    permanently stop draining for the rest of the process's life.
    CancelledError (raised by stop()'s future.cancel(), not caught by
    `except Exception`) is deliberately left to propagate, since that's
    how this loop is meant to end.
    """
    settings = load_celery_settings()
    while True:
        try:
            await _drain_outbox_from_worker()
        except Exception:
            logger.exception("Outbox drain tick failed; will retry on the next tick.")
        await asyncio.sleep(settings.DRAIN_OUTBOX_INTERVAL_SECONDS)


async def _drain_outbox_from_worker() -> None:
    """
    Resolves this worker process's own SqlaOutboxRepository (bound to a
    fresh, REQUEST-scoped DB session -- see WorkerProvider) and the
    current CELERY_OUTBOX_RETAIN_AFTER_RELAY setting, then delegates to
    the plain, directly-testable _drain_outbox() below.
    """
    settings = load_celery_settings()
    container = get_worker_container()
    async with container() as request_container:
        outbox = await request_container.get(SqlaOutboxRepository)
        await _drain_outbox(outbox, celery_app, retain_after_relay=settings.OUTBOX_RETAIN_AFTER_RELAY)


async def _drain_outbox(
    outbox: SqlaOutboxRepository,
    celery: Celery,
    *,
    retain_after_relay: bool,
) -> None:
    """
    For each still-pending OutboxMessage row: relays it to Celery via the
    exact same DISPATCH_HANDLER_TASK_NAME task HybridEventDispatcher.dispatch()
    used to publish to directly before the outbox existed, then always
    marks it processed. Only additionally deletes it when
    retain_after_relay is False -- see docs/plans/4-transactional-outbox.md,
    Confirmed Decision #2. Takes the repository and Celery client as
    plain parameters (rather than reaching for module globals) so this
    routing logic is testable with fakes, with no real DB session or
    broker connection needed.

    task_id is set to the outbox row's own id -- without it, Celery would
    generate an unrelated random UUID, leaving no way to correlate a
    Celery task/Redis result key back to the Postgres row that caused it.
    Sharing one id across both makes the two, together, a full audit
    trail for a single relayed event.

    commit() runs once, after every message in the batch, rather than
    once per message -- see SqlaOutboxRepository.get_pending()/commit()
    for why: committing partway through would release this batch's own
    row locks early, letting a concurrent drain loop (there's more than
    one worker process polling -- see get_pending()) see and relay the
    same not-yet-processed rows a second time.
    """
    messages = await outbox.get_pending()
    for message in messages:
        logger.info("Draining outbox row -> %s : %s", message.event_type, message.handler_type)
        celery.send_task(
            DISPATCH_HANDLER_TASK_NAME,
            task_id=str(message.id_),
            kwargs={
                "event_type": message.event_type,
                "handler_type": message.handler_type,
                "payload": message.payload,
            },
        )
        await outbox.mark_processed(message)
        if not retain_after_relay:
            await outbox.delete(message)
    if messages:
        await outbox.commit()
