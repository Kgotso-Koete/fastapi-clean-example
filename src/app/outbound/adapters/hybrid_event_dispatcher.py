import logging
from collections.abc import Sequence
from typing import Any, NewType

from app.core.commands.ports.outbox_repository import OutboxRepository
from app.core.common.events.domain_event import DomainEvent
from app.core.common.ports.event_handler import EventHandler
from app.outbound.adapters.event_serialization import dotted_path

logger = logging.getLogger(__name__)

# The single Celery task name every background handler is eventually
# published under -- by app.main.worker's outbox drain loop, not by this
# dispatcher itself. Must match the "name=" on the
# @celery_app.task(...) decorator in app.main.worker.tasks. Defined here
# (in `outbound`) rather than duplicated, since `main` may import
# `outbound` (just not the other way around) -- drain_outbox imports this
# constant from here instead of hardcoding the string a second time.
DISPATCH_HANDLER_TASK_NAME = "app.events.dispatch_handler"

# Wraps CelerySettings.ENABLED as a distinct, DI-resolvable type (mirroring
# CookieName in app.outbound.auth_ctx.cookie_manager) -- HybridEventDispatcher
# lives in `outbound`, which may not import app.main.config.settings
# directly, so main/ioc/outbound.py's CeleryProvider reads the setting and
# wraps it into this type instead.
CeleryEnabled = NewType("CeleryEnabled", bool)


class HybridEventDispatcher:
    """
    Fulfills the EventDispatcher port. Reads DISPATCH_MODE off each
    individual handler:
      - "sync": awaited inline, in this process, blocking the caller.
      - "background": recorded via stage() (called BEFORE the caller's
        commit) into the transactional outbox, then relayed to Celery
        later by app.main.worker's outbox drain loop -- never published
        directly from this process. This closes the delivery
        gap a direct send_task()-after-commit would otherwise leave: a
        crash between commit and publish can no longer silently drop the
        event, since the outbox row already committed atomically with the
        domain change. See docs/plans/4-transactional-outbox.md.

    A single event can have a mix of both kinds of handlers -- each is
    routed independently. The caller is expected to call stage(events)
    before its own flush()/commit(), then dispatch(events) after, e.g.:

        self._user_tx_storage.add(user)
        await self._event_dispatcher.stage(user.collect_events())
        await self._flusher.flush()
        await self._transaction_manager.commit()
        await self._event_dispatcher.dispatch(user.collect_events())
    """

    def __init__(
        self,
        handler_registry: dict[type[DomainEvent], Sequence[EventHandler[Any]]],
        celery_enabled: CeleryEnabled,
        outbox: OutboxRepository,
    ) -> None:
        self._handlers = handler_registry
        self._celery_enabled = celery_enabled
        self._outbox = outbox

    async def stage(self, events: list[DomainEvent]) -> None:
        """
        Call BEFORE flush()/commit(). Writes one outbox row per (event,
        "background" handler) pair so it commits atomically with the
        domain change. No-op when Celery is disabled: there's no broker
        to relay to, and dispatch()'s inline fallback already runs every
        handler synchronously with no delivery gap to close.
        """
        if not self._celery_enabled:
            return
        for event in events:
            # Handlers not registered for this event's type are simply
            # skipped -- an event with no subscribers is not an error.
            for handler in self._handlers.get(type(event), ()):
                if handler.DISPATCH_MODE == "background":
                    logger.info(
                        "Staging (background) %s -> %s",
                        type(event).__name__,
                        type(handler).__name__,
                    )
                    self._outbox.add(
                        event_type=dotted_path(type(event)),
                        handler_type=dotted_path(type(handler)),
                        payload=event.to_payload(),
                    )

    async def dispatch(self, events: list[DomainEvent]) -> None:
        """
        Call AFTER commit(). Runs "sync" handlers inline, as always. Also
        runs "background" handlers inline, but only as a fallback when
        Celery is disabled -- when Celery is enabled, "background"
        handlers are skipped here entirely, since stage() already
        recorded them durably before commit and drain_outbox relays them
        afterward; running them here too would run them twice.
        """
        for event in events:
            for handler in self._handlers.get(type(event), ()):
                if handler.DISPATCH_MODE == "sync" or not self._celery_enabled:
                    logger.info(
                        "Dispatching (sync) %s -> %s",
                        type(event).__name__,
                        type(handler).__name__,
                    )
                    await handler.handle(event)
