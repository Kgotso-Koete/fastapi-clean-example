"""
How Organizations plugs into the app (docs/plans/16-modular-monolith.md, "A
unit's interface" and Decision 13): the names the registry in
src/app/base/main/modules.py reads from every unit. This file imports nothing
from src/app/base/main/ (the unit-order import rule forbids it); mypy checks it
against the registry's Unit Protocol through the UNITS list there.

Organizations owns organizations, their members and their invitations.
Everything it owns lives here: its core, routes, adapters, table mappings,
providers and development data.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from dishka import Provider
from fastapi import APIRouter

from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.ports.event_handler import EventHandler
from app.modules.organizations.inbound.http.private_api.router import make_organizations_router
from app.modules.organizations.inbound.http.public_api.router import (
    make_organizations_router as make_public_organizations_router,
)
from app.modules.organizations.main.ioc.providers import OrganizationsPublicApiProvider, OrganizationsWebProvider
from app.modules.organizations.main.seed import seed_organizations
from app.modules.organizations.outbound.persistence_sqla.mappings.organization import map_organizations_table
from app.modules.organizations.outbound.persistence_sqla.mappings.organization_membership import (
    map_organization_memberships_table,
)

# The name other units use for this one in their NEEDS.
NAME: str = "organizations"

# Organizations needs no other unit: it depends only on base.
NEEDS: tuple[str, ...] = ()

# It handles no events at any entrypoint. It raises one,
# OrganizationInvitationCreatedEvent, which Notifications handles. The type is
# spelled out rather than imported as the registry's Subscriptions alias, which
# lives in src/app/base/main/ and may not be imported here.
WEB_SUBSCRIPTIONS: Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]] = {}
CLI_SUBSCRIPTIONS: Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]] = {}

# Its dishka providers at each entrypoint (main/ioc/providers.py): the web app's
# binds its ports and use cases, the public API's what its two read-only routes
# need. The CLI and the worker run none of its code, so they have none.
WEB_PROVIDERS: tuple[type[Provider], ...] = (OrganizationsWebProvider,)
PUBLIC_API_PROVIDERS: tuple[type[Provider], ...] = (OrganizationsPublicApiProvider,)
CLI_PROVIDERS: tuple[type[Provider], ...] = ()
WORKER_PROVIDERS: tuple[type[Provider], ...] = ()

# Its table-mapping functions, called by map_tables() after base's own tables:
# organizations first, then organization_memberships, today's order. They live
# in this module's outbound/persistence_sqla/mappings/. The type is spelled out
# rather than imported as the registry's TableMapping alias, which lives in
# src/app/base/main/.
TABLE_MAPPINGS: tuple[Callable[[], None], ...] = (map_organizations_table, map_organization_memberships_table)

# Its development-data seed functions (main/seed.py), which scripts/seed_db.py
# runs after base's own users and API keys when SEED_DB_WITH_TEST_DATA=true. The
# type is spelled out rather than imported as the registry's Seed Protocol,
# which lives in src/app/base/main/.
SEEDS: tuple[Callable[..., Awaitable[None]], ...] = (seed_organizations,)


# Its private routers, under /api/v1 in the web app. Every route requires the
# session cookie (APIKeyCookie, which also puts the cookie security scheme in
# the OpenAPI document), so the router takes the cookie's name. The routes
# live in this module's inbound/http/private_api/.
def make_web_routers(*, cookie_name: str) -> Sequence[APIRouter]:
    return (make_organizations_router(cookie_name=cookie_name),)


# Its public routers, under /public/v1 in the public API: the two read-only
# routes an API key may call. They live in this module's
# inbound/http/public_api/.
def make_public_routers() -> Sequence[APIRouter]:
    return (make_public_organizations_router(),)
