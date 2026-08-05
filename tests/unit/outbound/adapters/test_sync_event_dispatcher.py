from unittest.mock import ANY, AsyncMock

import pytest

from app.core.common.events.domain_event import DomainEvent
from app.outbound.adapters.sync_event_dispatcher import SyncEventDispatcher


class _TestEventA(DomainEvent):
    pass


class _TestEventB(DomainEvent):
    pass


class TestSyncEventDispatcher:
    @pytest.mark.asyncio
    async def test_dispatches_events_to_registered_handlers_sequentially(self) -> None:
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        handler3 = AsyncMock()

        registry = {
            _TestEventA: [handler1, handler2],
            _TestEventB: [handler3],
        }
        dispatcher = SyncEventDispatcher(handler_registry=registry)  # type: ignore[arg-type]

        event_a = _TestEventA(occurred_at=ANY)
        event_b = _TestEventB(occurred_at=ANY)

        await dispatcher.dispatch([event_a, event_b])

        handler1.handle.assert_called_once_with(event_a)
        handler2.handle.assert_called_once_with(event_a)
        handler3.handle.assert_called_once_with(event_b)

    @pytest.mark.asyncio
    async def test_ignores_events_with_no_registered_handlers(self) -> None:
        registry = {}  # type: ignore[var-annotated]
        dispatcher = SyncEventDispatcher(handler_registry=registry)

        event = _TestEventA(occurred_at=ANY)

        # Should not raise any errors
        await dispatcher.dispatch([event])
