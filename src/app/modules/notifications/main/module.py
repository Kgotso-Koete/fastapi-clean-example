"""
How Notifications plugs into the app (docs/plans/16-modular-monolith.md, "A
unit's interface" and Decision 13): the names the registry in
src/app/base/main/modules.py reads from every unit. This file imports nothing
from src/app/base/main/ (the unit-order import rule forbids it); mypy checks it
against the registry's Unit Protocol through the UNITS list there.

Notifications reacts to other units' events by sending email. Nothing depends
on it, so removing it from UNITS drops every subscription below and the rest
of the app still starts (plan 16, user story 4).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from dishka import Provider
from fastapi import APIRouter

from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.events.user_registered import UserRegisteredEvent
from app.base.core.common.ports.event_handler import EventHandler
from app.modules.notifications.core.common.events.handlers.send_organization_invitation_email import (
    SendOrganizationInvitationEmail,
)
from app.modules.notifications.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.modules.notifications.main.ioc.providers import (
    NotificationsCliProvider,
    NotificationsWebProvider,
    NotificationsWorkerProvider,
)
from app.modules.organizations.core.api import OrganizationInvitationCreatedEvent

# The name other units use for this one in their NEEDS.
NAME: str = "notifications"

# The units Notifications needs at run time: Organizations, whose invitation
# event it handles, and shared, whose email binding its handlers send through
# (it imports nothing from shared, so only this declaration records the need).
# Listed in that order, so a registry missing both names Organizations first.
NEEDS: tuple[str, ...] = ("organizations", "shared")

# The web app's event subscriptions: every email this module sends. The type is
# spelled out rather than imported as the registry's Subscriptions alias, which
# lives in src/app/base/main/ and may not be imported here.
WEB_SUBSCRIPTIONS: Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]] = {
    UserRegisteredEvent: (SendWelcomeEmail,),
    OrganizationInvitationCreatedEvent: (SendOrganizationInvitationEmail,),
}

# The CLI's event subscriptions: the CLI creates users but has no organization
# commands, so only the welcome email.
CLI_SUBSCRIPTIONS: Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]] = {
    UserRegisteredEvent: (SendWelcomeEmail,),
}

# The dishka providers that bind its handlers at each entrypoint that runs
# them (main/ioc/providers.py says which handlers each binds). The public API
# runs none of them, so its list is empty.
WEB_PROVIDERS: tuple[type[Provider], ...] = (NotificationsWebProvider,)
PUBLIC_API_PROVIDERS: tuple[type[Provider], ...] = ()
CLI_PROVIDERS: tuple[type[Provider], ...] = (NotificationsCliProvider,)
WORKER_PROVIDERS: tuple[type[Provider], ...] = (NotificationsWorkerProvider,)

# Its table-mapping functions: none. Notifications stores nothing of its own.
TABLE_MAPPINGS: tuple[Callable[[], None], ...] = ()

# Its development-data seed functions: none. Notifications stores nothing of its own.
SEEDS: tuple[Callable[..., Awaitable[None]], ...] = ()


# Its private routers: none. Notifications only reacts to events. The
# registry asks every unit, so the function is here and returns nothing.
def make_web_routers(*, cookie_name: str) -> Sequence[APIRouter]:
    return ()


# Its public routers: none, for the same reason.
def make_public_routers() -> Sequence[APIRouter]:
    return ()
