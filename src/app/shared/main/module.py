"""
How shared plugs into the app (docs/plans/16-modular-monolith.md, "A unit's
interface" and Decision 13): the names the registry in
src/app/base/main/modules.py reads from every unit. This file imports nothing
from src/app/base/main/ (the unit-order import rule forbids it); mypy checks it
against the registry's Unit Protocol through the UNITS list there.

shared holds our implementations of technical capabilities, so far email: it
binds base's EmailSender port to an adapter. It serves no routes, handles no
events and stores nothing; it only supplies bindings.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from dishka import Provider
from fastapi import APIRouter

from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.ports.event_handler import EventHandler
from app.shared.main.ioc.providers import SharedEmailProvider

# The name other units use for this one in their NEEDS.
NAME: str = "shared"

# The units shared needs at run time: none. It only implements base's ports.
NEEDS: tuple[str, ...] = ()

# Its event subscriptions: none. shared handles no events. The type is spelled
# out rather than imported as the registry's Subscriptions alias, which lives in
# src/app/base/main/ and may not be imported here.
WEB_SUBSCRIPTIONS: Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]] = {}
CLI_SUBSCRIPTIONS: Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]] = {}

# The email binding, at each entrypoint that sends email: the web app (its
# error alerting and Notifications' handlers), the CLI and the worker
# (Notifications' handlers). The public API sends none, so its list is empty.
WEB_PROVIDERS: tuple[type[Provider], ...] = (SharedEmailProvider,)
PUBLIC_API_PROVIDERS: tuple[type[Provider], ...] = ()
CLI_PROVIDERS: tuple[type[Provider], ...] = (SharedEmailProvider,)
WORKER_PROVIDERS: tuple[type[Provider], ...] = (SharedEmailProvider,)

# Its table-mapping functions: none. shared stores nothing of its own.
TABLE_MAPPINGS: tuple[Callable[[], None], ...] = ()

# Its development-data seed functions: none. shared stores nothing of its own.
SEEDS: tuple[Callable[..., Awaitable[None]], ...] = ()


# Its private routers: none. shared serves no routes. The registry asks every
# unit, so the function is here and returns nothing.
def make_web_routers(*, cookie_name: str) -> Sequence[APIRouter]:
    return ()


# Its public routers: none, for the same reason.
def make_public_routers() -> Sequence[APIRouter]:
    return ()
