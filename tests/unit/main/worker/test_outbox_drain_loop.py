import asyncio
from unittest.mock import AsyncMock

import pytest

from app.main.config.settings import CelerySettings
from app.main.worker import outbox_drain_loop
from app.main.worker.outbox_drain_loop import _run_forever


class TestRunForever:
    """
    _run_forever() is the coroutine app.main.worker.outbox_drain_loop.start()
    spawns on the worker process's persistent loop -- see
    docs/plans/4-transactional-outbox.md's "Why not a Celery Beat task"
    section for why this replaced a Celery Beat schedule entirely: it must
    never be a Celery task itself, or every tick (not just real drains)
    would show up in Flower/Redis again.
    """

    @pytest.mark.asyncio
    async def test_survives_a_failed_tick_and_keeps_ticking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # One bad tick (e.g. a transient DB blip) must not permanently
        # stop draining for the rest of the process's life -- the second,
        # successful tick proves the loop kept going past the first
        # tick's exception instead of propagating it and dying.
        tick = AsyncMock(side_effect=[RuntimeError("boom"), None, asyncio.CancelledError()])
        monkeypatch.setattr(outbox_drain_loop, "_drain_outbox_from_worker", tick)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        with pytest.raises(asyncio.CancelledError):
            await _run_forever()

        assert tick.call_count == 3

    @pytest.mark.asyncio
    async def test_sleeps_the_configured_interval_between_ticks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(outbox_drain_loop, "_drain_outbox_from_worker", AsyncMock())
        monkeypatch.setattr(
            outbox_drain_loop, "load_celery_settings", lambda: CelerySettings(DRAIN_OUTBOX_INTERVAL_SECONDS=7.0)
        )
        # Cancelling from inside sleep() (rather than the tick) proves the
        # loop actually reaches and awaits sleep() after a successful tick,
        # not just after a failed one.
        sleep = AsyncMock(side_effect=asyncio.CancelledError())
        monkeypatch.setattr(asyncio, "sleep", sleep)

        with pytest.raises(asyncio.CancelledError):
            await _run_forever()

        sleep.assert_called_once_with(7.0)
