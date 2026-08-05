import asyncio
from unittest.mock import ANY, AsyncMock

import pytest

from app.core.common.events.domain_event import DomainEvent
from app.outbound.adapters.background_event_dispatcher import BackgroundEventDispatcher


class _TestEvent(DomainEvent):
    pass


class TestBackgroundEventDispatcher:
    @pytest.mark.asyncio
    async def test_dispatches_events_in_background_tasks(self) -> None:
        handler = AsyncMock()
        registry = {_TestEvent: [handler]}
        dispatcher = BackgroundEventDispatcher(handler_registry=registry)  # type: ignore[arg-type]

        event = _TestEvent(occurred_at=ANY)

        await dispatcher.dispatch([event])

        # handler.handle should NOT be called immediately, but should be scheduled
        assert handler.handle.call_count == 0

        # yield control to the event loop so background tasks can run
        await asyncio.sleep(0)

        handler.handle.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_safe_handle_catches_handler_exceptions(self) -> None:
        handler = AsyncMock()
        handler.handle.side_effect = ValueError("Handler failed")

        registry = {_TestEvent: [handler]}
        dispatcher = BackgroundEventDispatcher(handler_registry=registry)  # type: ignore[arg-type]

        event = _TestEvent(occurred_at=ANY)

        await dispatcher.dispatch([event])

        # yield control, exception should be swallowed by _safe_handle
        await asyncio.sleep(0)

        handler.handle.assert_called_once_with(event)
