import logging
from typing import Any

from app.core.common.events.domain_event import DomainEvent
from app.main.worker.celery_app import celery_app
from app.main.worker.container import get_worker_container
from app.main.worker.loop_runtime import run_coroutine
from app.outbound.adapters.event_serialization import import_from_dotted_path

logger = logging.getLogger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]  # celery's task decorator ships without full type stubs
    name="app.events.dispatch_handler",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def dispatch_event_handler_task(
    self: Any,
    *,
    event_type: str,
    handler_type: str,
    payload: dict[str, Any],
) -> None:
    """
    The single Celery task every "background"-mode handler is published
    under -- HybridEventDispatcher (in the web process) sends to this task
    by NAME only, and never imports this module directly. Celery's default
    worker pool has no native async support, so the actual async work runs
    via run_coroutine() on this process's persistent event loop rather
    than being awaited directly here.
    """
    try:
        run_coroutine(_dispatch(event_type, handler_type, payload))
    except Exception as exc:
        logger.exception("Background event handler failed: %s -> %s", event_type, handler_type)
        # Celery retries with the backoff configured above (max_retries,
        # default_retry_delay) rather than the task just failing outright
        # on the first transient error (e.g. a flaky SMTP connection).
        raise self.retry(exc=exc) from exc


async def _dispatch(event_type: str, handler_type: str, payload: dict[str, Any]) -> None:
    """
    Reconstructs the event and resolves the handler from the dotted-path
    strings the message carried, then runs the handler -- the same
    handler.handle(event) call HybridEventDispatcher would make for a
    "sync" handler, just running here, in the worker process, instead.
    """
    event_cls: type[DomainEvent] = import_from_dotted_path(event_type)
    handler_cls = import_from_dotted_path(handler_type)
    event = event_cls.from_payload(payload)

    container = get_worker_container()
    # Opens one Scope.REQUEST child container for this task, mirroring how
    # the web process's ContainerMiddleware opens one per HTTP request.
    async with container() as request_container:
        handler = await request_container.get(handler_cls)
        await handler.handle(event)
