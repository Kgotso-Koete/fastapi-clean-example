from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.common.events.domain_event import DomainEvent
from app.outbound.adapters.event_serialization import dotted_path
from app.outbound.adapters.hybrid_event_dispatcher import CeleryEnabled, HybridEventDispatcher


class _TestEvent(DomainEvent):
    pass


def _make_handler(dispatch_mode: str) -> AsyncMock:
    """
    A real handler class declares DISPATCH_MODE as a class attribute (see
    EventHandler port); AsyncMock lets us set the same attribute on a mock
    so HybridEventDispatcher can read it exactly the way it would on a
    real handler.
    """
    handler = AsyncMock()
    handler.DISPATCH_MODE = dispatch_mode
    return handler


class TestHybridEventDispatcherStage:
    """
    stage() is called BEFORE the caller's flush()/commit(). It writes one
    outbox row per (event, "background" handler) pair via the injected
    OutboxRepository, so the outbox insert and the domain change commit
    atomically in the same transaction -- it never talks to Celery
    directly. See docs/plans/4-transactional-outbox.md.
    """

    @pytest.mark.asyncio
    async def test_stages_one_row_per_background_handler(self) -> None:
        handler = _make_handler("background")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        # A real datetime, not a placeholder -- staging calls
        # event.to_payload(), which needs a real occurred_at to encode.
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.stage([event])

        outbox.add.assert_called_once_with(
            event_type=dotted_path(_TestEvent),
            handler_type=dotted_path(type(handler)),
            payload=event.to_payload(),
        )
        # Staging never runs the handler itself -- only dispatch() does,
        # and only for sync/fallback cases.
        handler.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_stage_sync_handlers(self) -> None:
        handler = _make_handler("sync")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.stage([event])

        # Sync handlers run inline from dispatch() after commit -- staging
        # them here too would make them run twice.
        outbox.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_nothing_when_celery_disabled(self) -> None:
        # With no broker to relay to, there's nothing worth durably
        # recording -- dispatch()'s inline fallback already covers this
        # deployment mode with no gap to close.
        handler = _make_handler("background")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(False),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.stage([event])

        outbox.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_events_with_no_registered_handlers(self) -> None:
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        # Should not raise, even though nothing is registered for this event.
        await dispatcher.stage([event])

        outbox.add.assert_not_called()


class TestHybridEventDispatcherDispatch:
    """
    dispatch() is called AFTER commit(). It always runs "sync" handlers
    inline. "background" handlers are only run inline here as the
    Celery-disabled fallback -- when Celery is enabled, they were already
    staged pre-commit by stage(), and app.main.worker's outbox drain loop
    relays them later, so dispatch() must not run or re-publish them
    itself.
    """

    @pytest.mark.asyncio
    async def test_awaits_sync_handlers_inline(self) -> None:
        handler = _make_handler("sync")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        handler.handle.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_skips_background_handlers_when_celery_enabled(self) -> None:
        # Already staged pre-commit -- running it again here would run it
        # twice (once inline, once later via the relay).
        handler = _make_handler("background")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        handler.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_sync_and_background_handlers_on_the_same_event(self) -> None:
        # A single event (like the OrderPlaced example) can have one
        # handler that must block the response and another that can lag --
        # both must be routed correctly from a single stage()+dispatch()
        # pair, with no special casing needed by the caller.
        sync_handler = _make_handler("sync")
        background_handler = _make_handler("background")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [sync_handler, background_handler]},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        sync_handler.handle.assert_called_once_with(event)
        background_handler.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_events_with_no_registered_handlers(self) -> None:
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={},
            celery_enabled=CeleryEnabled(True),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        # Should not raise, even though nothing is registered for this event.
        await dispatcher.dispatch([event])


class TestHybridEventDispatcherWithCeleryDisabled:
    """
    CeleryEnabled(False) is how a deployment with no Redis/worker
    infrastructure at all (e.g. to save cost) tells the dispatcher not to
    rely on Celery being reachable. A "background" handler must still run
    -- just inline, like a "sync" one -- rather than erroring or silently
    dropping the event.
    """

    @pytest.mark.asyncio
    async def test_background_handler_runs_inline_instead_of_using_celery(self) -> None:
        handler = _make_handler("background")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(False),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        handler.handle.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_sync_handler_is_unaffected(self) -> None:
        handler = _make_handler("sync")
        outbox = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_enabled=CeleryEnabled(False),
            outbox=outbox,
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        handler.handle.assert_called_once_with(event)
