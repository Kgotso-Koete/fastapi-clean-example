import asyncio
import logging
from collections.abc import Sequence
from typing import Any, NewType

from celery import Celery

from app.core.common.events.domain_event import DomainEvent
from app.core.common.ports.event_handler import EventHandler
from app.outbound.adapters.event_serialization import dotted_path

logger = logging.getLogger(__name__)

# The single Celery task name every background handler is published under.
# Must match the "name=" on the @celery_app.task(...) decorator in
# app.main.worker.tasks -- HybridEventDispatcher never imports that module
# directly (outbound may not import main), so this string is the only
# contract tying the two together.
DISPATCH_HANDLER_TASK_NAME = "app.events.dispatch_handler"

# Wraps CelerySettings.ENABLED as a distinct, DI-resolvable type (mirroring
# CookieName in app.outbound.auth_ctx.cookie_manager) -- HybridEventDispatcher
# lives in `outbound`, which may not import app.main.config.settings
# directly, so main/ioc/outbound.py's CeleryProvider reads the setting and
# wraps it into this type instead.
CeleryEnabled = NewType("CeleryEnabled", bool)


class HybridEventDispatcher:
    """
    Fulfills the EventDispatcher port. Unlike the old SyncEventDispatcher/
    BackgroundEventDispatcher (one dispatch strategy for the whole app),
    this dispatcher reads DISPATCH_MODE off each individual handler and
    runs it accordingly:
      - "sync": awaited inline, in this process, blocking the caller.
      - "background": published to Celery by task name only, to be picked
        up and actually executed later by a worker process.

    A single event can have a mix of both kinds of handlers -- each is
    routed independently, so the caller (e.g. SignUp.execute()) just calls
    dispatch(events) once and doesn't need to know or care which handlers
    are sync vs background.
    """

    def __init__(
        self,
        handler_registry: dict[type[DomainEvent], Sequence[EventHandler[Any]]],
        celery_app: Celery,
        celery_enabled: CeleryEnabled,
    ) -> None:
        self._handlers = handler_registry
        self._celery_app = celery_app
        self._celery_enabled = celery_enabled

    async def dispatch(self, events: list[DomainEvent]) -> None:
        for event in events:
            # Handlers not registered for this event's type are simply
            # skipped -- an event with no subscribers is not an error.
            for handler in self._handlers.get(type(event), ()):
                # With Celery disabled (no Redis/worker in this deployment
                # at all -- e.g. to save cost), every handler runs inline,
                # regardless of its own DISPATCH_MODE: a "background"
                # handler still gets to run, just without the "don't block
                # the response" benefit, rather than erroring or being
                # silently dropped because there's no broker to publish to.
                if handler.DISPATCH_MODE == "sync" or not self._celery_enabled:
                    logger.info(
                        "Dispatching (sync) %s -> %s",
                        type(event).__name__,
                        type(handler).__name__,
                    )
                    await handler.handle(event)
                else:
                    logger.info(
                        "Dispatching (background) %s -> %s",
                        type(event).__name__,
                        type(handler).__name__,
                    )
                    kwargs = {
                        # Class objects can't cross a process boundary as a
                        # JSON message -- dotted_path() turns each one into
                        # a plain string the worker's task can resolve back
                        # with import_from_dotted_path().
                        "event_type": dotted_path(type(event)),
                        "handler_type": dotted_path(type(handler)),
                        "payload": event.to_payload(),
                    }
                    # In production, this process's own Celery object never
                    # has the task registered on it (only the worker's
                    # own celery_app does -- see app.main.worker.tasks), so
                    # this is always None and send_task() below is what
                    # actually runs. It's only non-None when something
                    # (deliberately, in eager-mode tests) points this
                    # dispatcher at the SAME Celery object the task is
                    # registered on -- calling apply_async() on that bound
                    # task, rather than send_task() by name, is required
                    # for task_always_eager to have any effect: Celery
                    # documents/warns that send_task() ignores it entirely
                    # ("AlwaysEagerIgnored: task_always_eager has no effect
                    # on send_task").
                    registered_task = self._celery_app.tasks.get(DISPATCH_HANDLER_TASK_NAME)
                    if registered_task is not None:
                        await asyncio.to_thread(registered_task.apply_async, kwargs=kwargs)
                    else:
                        # send_task() talks to Redis over a blocking
                        # socket call. Running it in a thread (rather than
                        # awaiting it directly) keeps a slow or unavailable
                        # broker from stalling this coroutine's event loop.
                        await asyncio.to_thread(
                            self._celery_app.send_task,
                            DISPATCH_HANDLER_TASK_NAME,
                            kwargs=kwargs,
                        )
