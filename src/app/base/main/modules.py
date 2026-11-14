"""
The registry of units (docs/plans/16-modular-monolith.md, "The registry"): the
one place the composition root learns which units make up the app -- the
modules under src/app/modules/ and, from Step 5, src/app/shared/.

Built test-first, one piece at a time. The pieces so far: the "needs" check,
combining event subscriptions, each unit's providers per entrypoint, combining
each unit's routers, its table mappings and its seeds, and the registry list
itself (UNITS). The "needs" check:
the app refuses to start when a registered unit needs a unit that isn't
registered (plan 16, user story 4). Import rules can't catch that, because a
unit can need another at run time without importing it (Notifications needs
shared's EmailSender binding but imports only base's EmailSender port).
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from dishka import AsyncContainer, Provider
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.common.entities.types_ import UserId
from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.ports.event_handler import EventHandler
from app.modules.notifications.main import module as notifications
from app.modules.organizations.main import module as organizations
from app.shared.main import module as shared

# One unit's event subscriptions at one entrypoint: each event class it listens
# to, mapped to the handler classes that handle it. Classes, not instances:
# dishka builds the instances when the entrypoint's container resolves them.
type Subscriptions = Mapping[type[DomainEvent], Sequence[type[EventHandler[Any]]]]

# One table-mapping function: called once at start-up, it maps a domain class
# onto its table with SQLAlchemy's imperative mapping (as map_users_table() in
# src/app/base/outbound/persistence_sqla/mappings/user.py does). It takes
# nothing and returns nothing.
type TableMapping = Callable[[], None]


class Seed(Protocol):
    """
    One unit's development-data seed function (plan 16, Step 4g).
    scripts/seed_db.py calls it when SEED_DB_WITH_TEST_DATA=true, after seeding
    base's own users and API keys, with keyword arguments only: the open session
    to add rows to (seed_db.py commits once, at the end), the seeded users' ids by
    username, and the app's container, so a unit can read its own settings.

    A Protocol, because a plain Callable can't spell keyword-only arguments.
    __call__ returns Awaitable[None] rather than being async, so a unit can
    spell SEEDS as tuple[Callable[..., Awaitable[None]], ...] without importing
    this (units may not import src/app/base/main/): an async function returns a
    coroutine, which is an Awaitable.
    """

    def __call__(
        self,
        *,
        session: AsyncSession,
        user_ids_by_username: Mapping[str, UserId],
        container: AsyncContainer,
    ) -> Awaitable[None]: ...


class Unit(Protocol):
    """
    What the registry reads from a unit (plan 16, Decision 13).

    A unit is the Python module at src/app/<unit>/main/module.py. It defines
    these names at module level and imports nothing from src/app/base/main/
    (the unit-order import rule forbids that); mypy checks each registered
    module against this Protocol structurally, so the type check stays without
    a forbidden import.

    Grows one name at a time, only when a test needs it (plan 16, finding 4).
    """

    # The unit's name, as other units refer to it in their NEEDS.
    NAME: str
    # The names of the units this unit needs at run time, whether or not it
    # imports them. Empty when it needs none.
    NEEDS: tuple[str, ...]
    # Its event subscriptions at each entrypoint that dispatches events: the
    # web app and the CLI. The public API dispatches none, and the worker runs
    # handlers by the import path stored in each outbox row, so neither has one.
    WEB_SUBSCRIPTIONS: Subscriptions
    CLI_SUBSCRIPTIONS: Subscriptions
    # Its dishka providers at each entrypoint that runs its code: classes, so
    # every container build gets fresh instances (collect_providers below).
    # Empty when it binds nothing there.
    WEB_PROVIDERS: tuple[type[Provider], ...]
    PUBLIC_API_PROVIDERS: tuple[type[Provider], ...]
    CLI_PROVIDERS: tuple[type[Provider], ...]
    WORKER_PROVIDERS: tuple[type[Provider], ...]
    # Its table-mapping functions, in the order map_tables() calls them after
    # base's own tables (at every entrypoint's start-up and in Alembic's env.py).
    # Empty when it has no tables of its own.
    TABLE_MAPPINGS: tuple[TableMapping, ...]
    # Its development-data seed functions, which scripts/seed_db.py runs after
    # base's own users and API keys (Step 4g). Empty when it seeds nothing.
    SEEDS: tuple[Seed, ...]

    # Its private routers in the web app, under /api/v1, in include order. A
    # function rather than a constant: each router needs the session cookie's
    # name, which comes from the web app's settings at start-up. Empty when it
    # serves no private routes.
    def make_web_routers(self, *, cookie_name: str) -> Sequence[APIRouter]: ...

    # Its routers in the public API, under /public/v1, in include order. No
    # cookie name: the public API never uses the session cookie, and each of its
    # routes declares its own API-key header. Empty when it serves no public routes.
    def make_public_routers(self) -> Sequence[APIRouter]: ...


class MissingUnitError(Exception):
    """Raised at start-up when a registered unit needs a unit that isn't registered."""


# The units base itself needs at run time (plan 16, "The registry" and "What
# goes where"): shared, whose EmailSender binding the web app's error alerting
# sends through. Declared here, not in shared's module.py: a deregistered unit's
# declarations are gone with it, so only base can say it needs one.
BASE_NEEDS: tuple[str, ...] = ("shared",)


def check_needs(units: Sequence[Unit]) -> None:
    """
    Refuses to start the app when a registered unit needs a unit that isn't
    registered, naming both, so the fix is obvious: register the missing unit,
    or deregister the one that needs it. It also refuses when a unit base itself
    needs (BASE_NEEDS) isn't registered, naming it. Returns nothing when every
    need is met.
    """
    registered = {unit.NAME for unit in units}
    for unit in units:
        for needed in unit.NEEDS:
            if needed not in registered:
                raise MissingUnitError(f"Unit {unit.NAME!r} needs unit {needed!r}, which is not registered.")
    # Then base's own needs, after every unit's, so a unit's missing need is
    # named first when both are missing.
    for needed in BASE_NEEDS:
        if needed not in registered:
            raise MissingUnitError(f"Base needs unit {needed!r}, which is not registered.")


def collect_subscriptions(
    per_unit: Iterable[Subscriptions],
) -> dict[type[DomainEvent], tuple[type[EventHandler[Any]], ...]]:
    """
    Combines every registered unit's subscriptions for one entrypoint into the
    single event-to-handlers mapping that entrypoint's handler registry serves.

    Units are read in registration order. When two units subscribe to the same
    event, the later unit's handlers are added after the earlier one's, never
    replacing them, so a fork's module can listen to an event alongside
    Notifications. With no units (Notifications removed), the result is empty,
    and the dispatcher already ignores events nobody handles.
    """
    combined: dict[type[DomainEvent], tuple[type[EventHandler[Any]], ...]] = {}
    for subscriptions in per_unit:
        for event_type, handler_types in subscriptions.items():
            combined[event_type] = (*combined.get(event_type, ()), *handler_types)
    return combined


def collect_providers(per_unit: Iterable[Sequence[type[Provider]]]) -> tuple[Provider, ...]:
    """
    Builds every registered unit's providers for one entrypoint, one fresh
    instance of each, for that entrypoint's container.

    Units are read in registration order, and each unit's providers in the
    order it lists them. The order matters: dishka lets a later provider
    replace an earlier one's binding of the same type without any error, so
    it must be the registry's order, never a shuffled one. With no units, the
    result is empty and the entrypoint keeps only base's own providers.
    """
    return tuple(provider() for providers in per_unit for provider in providers)


def collect_routers(per_unit: Iterable[Sequence[APIRouter]]) -> tuple[APIRouter, ...]:
    """
    Combines every registered unit's routers for one app into the single list
    that app includes: the web app's under /api/v1, and from Step 4c the public
    API's under /public/v1.

    Units are read in registration order, and each unit's routers in the order
    it lists them. The order is the include order, which sets the order of
    paths and tags in the OpenAPI document, so the snapshot tests in
    tests/base/characterisation/main/ catch any change to it. The caller builds
    the routers (each app's factories take different arguments), so this only
    combines them. With no units, the result is empty and the app serves only
    base's own routes.
    """
    return tuple(router for routers in per_unit for router in routers)


def collect_table_mappings(per_unit: Iterable[Sequence[TableMapping]]) -> tuple[TableMapping, ...]:
    """
    Combines every registered unit's table-mapping functions into the single
    list map_tables() calls after mapping base's own tables: at every
    entrypoint's start-up and in Alembic's env.py.

    Units are read in registration order, and each unit's functions in the
    order it lists them, so the tables are mapped in the same order every
    time (tests/base/characterisation/outbound/persistence_sqla/mappings/
    test_mapped_tables.py pins today's). With no units, the result is empty
    and only base's own tables are mapped.
    """
    return tuple(mapping for mappings in per_unit for mapping in mappings)


def collect_seeds(per_unit: Iterable[Sequence[Seed]]) -> tuple[Seed, ...]:
    """
    Combines every registered unit's seed functions into the single list
    scripts/seed_db.py runs after seeding base's own users and API keys.

    Units are read in registration order, and each unit's functions in the
    order it lists them. The registry lists a unit after the units it needs,
    so a unit's seeds find that data already there (Organizations' memberships
    need base's users). With no units, the result is empty and only base's own
    data is seeded.
    """
    return tuple(seed for seeds in per_unit for seed in seeds)


# The one code list of registered units (plan 16, Decision 2). Each entry is a
# unit's main/module.py, which mypy checks against Unit. The order is the
# registration order: shared first, which needs no unit and serves no routes;
# then Organizations, the order today's routers include it in; then
# Notifications, which needs Organizations and shared's email binding.
UNITS: tuple[Unit, ...] = (shared, organizations, notifications)
