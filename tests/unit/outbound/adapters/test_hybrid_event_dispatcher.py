from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.common.events.domain_event import DomainEvent
from app.outbound.adapters.event_serialization import dotted_path
from app.outbound.adapters.hybrid_event_dispatcher import (
    DISPATCH_HANDLER_TASK_NAME,
    CeleryEnabled,
    HybridEventDispatcher,
)


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


class TestHybridEventDispatcher:
    """
    HybridEventDispatcher is the adapter that fulfills the EventDispatcher
    port. For each handler registered against an event type, it reads that
    handler's own DISPATCH_MODE and either awaits it inline ("sync") or
    publishes it to Celery by task name ("background") -- it never imports
    app.main.worker.tasks itself (that would violate the outbound -> main
    layering rule), so we fake the Celery app with a plain Mock here.
    """

    @pytest.mark.asyncio
    async def test_awaits_sync_handlers_inline(self) -> None:
        handler = _make_handler("sync")
        celery_app = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(True),
        )
        # A real datetime, not a placeholder -- background dispatch calls
        # event.to_payload(), which needs a real occurred_at to encode.
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        # A sync handler runs directly, in-process -- no Celery involved.
        handler.handle.assert_called_once_with(event)
        celery_app.send_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_background_handlers_to_celery_by_task_name(self) -> None:
        handler = _make_handler("background")
        celery_app = Mock()
        # An empty (real) dict, not Mock's auto-generated attribute -- this
        # is what makes `self._celery_app.tasks.get(...)` correctly return
        # None, exercising the send_task() fallback path (see the
        # "locally registered" test below for the other branch).
        celery_app.tasks = {}
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(True),
        )
        # A real datetime, not a placeholder -- background dispatch calls
        # event.to_payload(), which needs a real occurred_at to encode.
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        # A background handler is never called directly in this process --
        # it's published to Celery by task name, to be run later by a
        # worker process.
        handler.handle.assert_not_called()
        celery_app.send_task.assert_called_once()
        args, kwargs = celery_app.send_task.call_args
        assert args[0] == DISPATCH_HANDLER_TASK_NAME
        # The message carries dotted paths (strings) for the event and
        # handler classes, plus the event's JSON-safe payload -- never the
        # class objects themselves, since those can't cross a process
        # boundary as a Celery message.
        assert kwargs["kwargs"]["event_type"] == dotted_path(_TestEvent)
        assert kwargs["kwargs"]["handler_type"] == dotted_path(type(handler))

    @pytest.mark.asyncio
    async def test_uses_the_locally_registered_task_when_available(self) -> None:
        # Celery's send_task() (by name) ignores task_always_eager entirely
        # -- confirmed by Celery's own runtime warning, "AlwaysEagerIgnored:
        # task_always_eager has no effect on send_task". Only calling
        # apply_async() on the actual bound Task object respects it. That
        # only happens when this process's own Celery object happens to
        # have the task registered on it too (which is the case in
        # eager-mode tests, where the test deliberately points
        # HybridEventDispatcher at the SAME object app.main.worker.tasks
        # registered the task against) -- in production, the web process's
        # own Celery object never has it registered, so this branch is
        # never taken there; send_task() by name is still what's used.
        handler = _make_handler("background")
        registered_task = Mock()
        celery_app = Mock()
        celery_app.tasks = {DISPATCH_HANDLER_TASK_NAME: registered_task}
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(True),
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        celery_app.send_task.assert_not_called()
        registered_task.apply_async.assert_called_once()
        _, kwargs = registered_task.apply_async.call_args
        assert kwargs["kwargs"]["event_type"] == dotted_path(_TestEvent)
        assert kwargs["kwargs"]["handler_type"] == dotted_path(type(handler))
        assert kwargs["kwargs"]["payload"] == event.to_payload()

    @pytest.mark.asyncio
    async def test_mixed_sync_and_background_handlers_on_the_same_event_both_run(self) -> None:
        # A single event (like the OrderPlaced example) can have one
        # handler that must block the response and another that can lag --
        # both must run from a single dispatch() call, with no special
        # casing needed by the caller.
        sync_handler = _make_handler("sync")
        background_handler = _make_handler("background")
        celery_app = Mock()
        celery_app.tasks = {}
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [sync_handler, background_handler]},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(True),
        )
        # A real datetime, not a placeholder -- background dispatch calls
        # event.to_payload(), which needs a real occurred_at to encode.
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        sync_handler.handle.assert_called_once_with(event)
        background_handler.handle.assert_not_called()
        celery_app.send_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_events_with_no_registered_handlers(self) -> None:
        celery_app = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(True),
        )
        # A real datetime, not a placeholder -- background dispatch calls
        # event.to_payload(), which needs a real occurred_at to encode.
        event = _TestEvent(occurred_at=datetime.now(UTC))

        # Should not raise, even though nothing is registered for this event.
        await dispatcher.dispatch([event])

        celery_app.send_task.assert_not_called()


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
        celery_app = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(False),
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        handler.handle.assert_called_once_with(event)
        celery_app.send_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_handler_is_unaffected(self) -> None:
        handler = _make_handler("sync")
        celery_app = Mock()
        dispatcher = HybridEventDispatcher(
            handler_registry={_TestEvent: [handler]},
            celery_app=celery_app,
            celery_enabled=CeleryEnabled(False),
        )
        event = _TestEvent(occurred_at=datetime.now(UTC))

        await dispatcher.dispatch([event])

        handler.handle.assert_called_once_with(event)
        celery_app.send_task.assert_not_called()
