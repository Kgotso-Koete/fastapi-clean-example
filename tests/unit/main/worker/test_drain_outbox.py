from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from app.main.worker.outbox_drain_loop import _drain_outbox
from app.outbound.adapters.hybrid_event_dispatcher import DISPATCH_HANDLER_TASK_NAME
from app.outbound.adapters.outbox_message import OutboxMessage


def _make_message(**overrides: object) -> OutboxMessage:
    """
    Builds a plausible pending OutboxMessage row without touching a real
    DB -- _drain_outbox() only ever reads these fields off whatever
    outbox.get_pending() hands it, so a plain in-memory instance is enough
    to exercise it.
    """
    defaults: dict[str, object] = {
        "id_": UUID("11111111-1111-1111-1111-111111111111"),
        "event_type": "app.core.common.events.user_registered:UserRegisteredEvent",
        "handler_type": "app.core.common.events.handlers.send_welcome_email:SendWelcomeEmail",
        "payload": {"user_id": "11111111-1111-1111-1111-111111111111"},
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return OutboxMessage(**defaults)  # type: ignore[arg-type]


class TestDrainOutbox:
    """
    _drain_outbox() is the async body app.main.worker.outbox_drain_loop's
    perpetual loop runs on every tick. For each still-pending OutboxMessage
    row (outbox.get_pending()), it relays the message to Celery via the
    exact same DISPATCH_HANDLER_TASK_NAME task that
    HybridEventDispatcher.dispatch() used to publish to directly before
    the outbox existed, then always marks the row processed. It only
    additionally deletes the row when CELERY_OUTBOX_RETAIN_AFTER_RELAY is
    False, and commits the whole batch exactly once at the end (not once
    per row -- see SqlaOutboxRepository.commit()'s docstring for why).
    See docs/plans/4-transactional-outbox.md, Confirmed Decision #2 and Step
    4. The repository and the Celery client are both passed in as fakes
    here -- neither a real DB session nor a real broker connection is
    needed to prove this routing logic.
    """

    @pytest.mark.asyncio
    async def test_relays_each_pending_message_to_celery_by_the_shared_task_name(self) -> None:
        message = _make_message()
        outbox = AsyncMock()
        outbox.get_pending.return_value = [message]
        celery = Mock()

        await _drain_outbox(outbox, celery, retain_after_relay=True)

        # kwargs shape must match send_task(...) byte-for-byte with what
        # HybridEventDispatcher.dispatch() used to call directly -- the
        # worker's dispatch_event_handler_task doesn't care who published
        # the message, only that the kwargs shape is exactly this.
        # task_id is set to the outbox row's own id so the Postgres row,
        # the Celery task, and the Redis result key all share one
        # identifier for auditing.
        celery.send_task.assert_called_once_with(
            DISPATCH_HANDLER_TASK_NAME,
            task_id=str(message.id_),
            kwargs={
                "event_type": message.event_type,
                "handler_type": message.handler_type,
                "payload": message.payload,
            },
        )

    @pytest.mark.asyncio
    async def test_marks_processed_but_does_not_delete_when_retention_is_on(self) -> None:
        message = _make_message()
        outbox = AsyncMock()
        outbox.get_pending.return_value = [message]
        celery = Mock()

        await _drain_outbox(outbox, celery, retain_after_relay=True)

        outbox.mark_processed.assert_called_once_with(message)
        # Retaining is the default (CELERY_OUTBOX_RETAIN_AFTER_RELAY=true)
        # so the row stays visible in Adminer instead of vanishing the
        # instant it's relayed.
        outbox.delete.assert_not_called()
        outbox.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_marks_processed_and_deletes_when_retention_is_off(self) -> None:
        message = _make_message()
        outbox = AsyncMock()
        outbox.get_pending.return_value = [message]
        celery = Mock()

        await _drain_outbox(outbox, celery, retain_after_relay=False)

        outbox.mark_processed.assert_called_once_with(message)
        outbox.delete.assert_called_once_with(message)
        outbox.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_nothing_when_there_are_no_pending_messages(self) -> None:
        outbox = AsyncMock()
        outbox.get_pending.return_value = []
        celery = Mock()

        await _drain_outbox(outbox, celery, retain_after_relay=True)

        celery.send_task.assert_not_called()
        outbox.mark_processed.assert_not_called()
        outbox.delete.assert_not_called()
        # No point opening/committing a transaction for a tick that found
        # nothing pending.
        outbox.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_relays_and_marks_every_message_in_a_multi_row_batch(self) -> None:
        # A single tick can find more than one row still pending -- each
        # must be relayed and marked independently, not just the first
        # one found.
        first = _make_message(id_=UUID("11111111-1111-1111-1111-111111111111"))
        second = _make_message(id_=UUID("22222222-2222-2222-2222-222222222222"))
        outbox = AsyncMock()
        outbox.get_pending.return_value = [first, second]
        celery = Mock()

        await _drain_outbox(outbox, celery, retain_after_relay=True)

        assert celery.send_task.call_count == 2
        outbox.mark_processed.assert_any_call(first)
        outbox.mark_processed.assert_any_call(second)
        # Exactly one commit for the whole batch, not one per row -- see
        # SqlaOutboxRepository.commit()'s docstring for why committing
        # partway through a batch would be wrong (it would release the
        # FOR UPDATE lock on this batch's own not-yet-processed rows
        # early, letting a concurrent drain loop see and relay them too).
        outbox.commit.assert_called_once()
