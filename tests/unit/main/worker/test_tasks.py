import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.common.entities.types_ import UserId
from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.events.user_registered import UserRegisteredEvent
from app.main.worker import container as worker_container
from app.main.worker.tasks import _dispatch
from app.outbound.adapters.event_serialization import dotted_path


@pytest.fixture(autouse=True)
def _reset_container() -> Iterator[None]:
    worker_container.clear_worker_container()
    yield
    worker_container.clear_worker_container()


class _FakeRequestContainer:
    """
    Stands in for the real per-task Dishka container. In production,
    request_container.get(handler_cls) resolves a real instance by type;
    here it just hands back whichever handler the test configured,
    regardless of what class is asked for.
    """

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    async def get(self, cls: type) -> Any:
        return self._handler


class _FakeRequestScope:
    """Stands in for the async context manager container() returns when opening a per-task scope."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    async def __aenter__(self) -> _FakeRequestContainer:
        return _FakeRequestContainer(self._handler)

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _FakeWorkerContainer:
    """Stands in for the real Dishka AsyncContainer that get_worker_container() returns."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def __call__(self) -> _FakeRequestScope:
        return _FakeRequestScope(self._handler)


class TestDispatch:
    """
    _dispatch() is the async function the Celery task body runs (via
    loop_runtime.run_coroutine). It has to: import the event/handler
    classes from the dotted-path strings the message carried, reconstruct
    the event from its JSON-safe payload, resolve the handler from this
    worker process's own container, and call handler.handle(event) --
    exactly what HybridEventDispatcher does for a "sync" handler, just
    running in a different process.
    """

    @pytest.mark.asyncio
    async def test_resolves_handler_and_calls_handle_with_the_reconstructed_event(self) -> None:
        handler = AsyncMock()
        worker_container.set_worker_container(_FakeWorkerContainer(handler))  # type: ignore[arg-type]

        event = UserRegisteredEvent(
            occurred_at=datetime.now(UTC),
            user_id=UserId(uuid.uuid4()),
            username="Alice",
            email="alice@example.com",
        )

        await _dispatch(
            event_type=dotted_path(UserRegisteredEvent),
            handler_type=dotted_path(SendWelcomeEmail),
            payload=event.to_payload(),
        )

        handler.handle.assert_called_once()
        (called_event,) = handler.handle.call_args.args
        # Not `is` -- the event that arrives here was rebuilt from a plain
        # dict via from_payload(), so it must be a genuinely new but equal
        # object, not the same instance dispatch() started with.
        assert called_event == event
