import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import pytest
from dishka import AsyncContainer, Provider, make_async_container
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.common.entities.types_ import UserId
from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.events.user_registered import UserRegisteredEvent
from app.base.core.common.ports.event_handler import EventHandler
from app.base.main.cli.provider import get_cli_providers
from app.base.main.ioc.provider_registry import get_providers
from app.base.main.ioc.public_api import get_public_api_providers
from app.base.main.modules import (
    UNITS,
    MissingUnitError,
    Seed,
    Subscriptions,
    TableMapping,
    Unit,
    check_needs,
    collect_providers,
    collect_routers,
    collect_seeds,
    collect_subscriptions,
    collect_table_mappings,
)
from app.base.main.worker.provider import get_worker_providers
from app.modules.notifications.core.common.events.handlers.send_organization_invitation_email import (
    SendOrganizationInvitationEmail,
)
from app.modules.notifications.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.modules.notifications.main.ioc.providers import (
    NotificationsCliProvider,
    NotificationsWebProvider,
    NotificationsWorkerProvider,
)
from app.modules.organizations.core.common.events.organization_invitation_created import (
    OrganizationInvitationCreatedEvent,
)
from app.modules.organizations.main import module as organizations
from app.modules.organizations.main.ioc.providers import OrganizationsPublicApiProvider, OrganizationsWebProvider
from app.modules.organizations.main.seed import seed_organizations
from app.modules.organizations.outbound.persistence_sqla.mappings.organization import map_organizations_table
from app.modules.organizations.outbound.persistence_sqla.mappings.organization_membership import (
    map_organization_memberships_table,
)
from app.shared.main import module as shared
from app.shared.main.ioc.providers import SharedEmailProvider


# A stand-in for a unit's main/module.py (docs/plans/16-modular-monolith.md,
# Decision 13). A real unit is a Python module whose NAME and NEEDS are
# module-level variables; a plain (not frozen) dataclass has the same kind of
# attributes, so mypy checks it against the Unit Protocol the same way.
@dataclass(slots=True, kw_only=True)
class FakeUnit:
    NAME: str
    NEEDS: tuple[str, ...] = ()
    # Empty by default: the "needs" tests don't subscribe to anything.
    WEB_SUBSCRIPTIONS: Subscriptions = field(default_factory=dict)
    CLI_SUBSCRIPTIONS: Subscriptions = field(default_factory=dict)
    # Empty by default too: only the provider tests below need any.
    WEB_PROVIDERS: tuple[type[Provider], ...] = ()
    PUBLIC_API_PROVIDERS: tuple[type[Provider], ...] = ()
    CLI_PROVIDERS: tuple[type[Provider], ...] = ()
    WORKER_PROVIDERS: tuple[type[Provider], ...] = ()
    TABLE_MAPPINGS: tuple[TableMapping, ...] = ()
    # Empty by default too: only the seeds test reads seeds, and it reads the real units.
    SEEDS: tuple[Seed, ...] = ()

    # No routes: only the router test reads routers, and it reads the real units.
    def make_web_routers(self, *, cookie_name: str) -> Sequence[APIRouter]:
        return ()

    def make_public_routers(self) -> Sequence[APIRouter]:
        return ()


def test_check_needs_passes_when_every_needed_unit_is_registered() -> None:
    # "notifications" needs "organizations", and both are registered, with
    # shared, which base itself needs.
    units = [
        FakeUnit(NAME="shared"),
        FakeUnit(NAME="organizations"),
        FakeUnit(NAME="notifications", NEEDS=("organizations",)),
    ]

    check_needs(units)  # no exception: nothing is missing


def test_check_needs_names_the_unit_and_the_unit_it_is_missing() -> None:
    # "notifications" needs "organizations", which is not registered: the app
    # must refuse to start and say which unit needs which (plan 16, user story 4).
    units = [FakeUnit(NAME="notifications", NEEDS=("organizations",))]

    with pytest.raises(
        MissingUnitError,
        match=re.escape("Unit 'notifications' needs unit 'organizations', which is not registered."),
    ):
        check_needs(units)


def test_check_needs_refuses_to_start_without_a_unit_base_needs() -> None:
    # base itself needs shared: its error alerting sends email through the
    # EmailSender binding shared supplies (plan 16, "The registry"). Every
    # registered unit's needs are met here, but shared isn't registered, so the
    # app must refuse to start and name it.
    units = [FakeUnit(NAME="organizations")]

    with pytest.raises(MissingUnitError, match=re.escape("Base needs unit 'shared', which is not registered.")):
        check_needs(units)


# A second handler for UserRegisteredEvent, standing in for a fork module that
# listens to the same event as Notifications. Never instantiated here: the
# registry deals in handler classes, and dishka builds the instances.
class RecordSignUp:
    DISPATCH_MODE: ClassVar[Literal["sync", "background"]] = "sync"

    async def handle(self, event: UserRegisteredEvent) -> None: ...


def test_collect_subscriptions_combines_every_units_subscriptions() -> None:
    # Two units, each subscribing to a different event: both are kept.
    combined = collect_subscriptions(
        [
            {UserRegisteredEvent: (SendWelcomeEmail,)},
            {OrganizationInvitationCreatedEvent: (SendOrganizationInvitationEmail,)},
        ],
    )

    assert combined == {
        UserRegisteredEvent: (SendWelcomeEmail,),
        OrganizationInvitationCreatedEvent: (SendOrganizationInvitationEmail,),
    }


def test_collect_subscriptions_keeps_every_handler_of_a_shared_event_in_registration_order() -> None:
    # Two units subscribing to the same event: the later one adds its handler
    # after the earlier one's, and never replaces it.
    combined = collect_subscriptions(
        [
            {UserRegisteredEvent: (SendWelcomeEmail,)},
            {UserRegisteredEvent: (RecordSignUp,)},
        ],
    )

    assert combined == {UserRegisteredEvent: (SendWelcomeEmail, RecordSignUp)}


def test_collect_subscriptions_with_no_units_is_empty() -> None:
    # No units registered (for example, Notifications removed): no event has a
    # handler, and the dispatcher already ignores events nobody handles.
    assert collect_subscriptions([]) == {}


def test_the_registry_lists_every_unit_in_registration_order() -> None:
    # The one code list of registered units (plan 16, Decision 2). shared comes
    # first: it needs no unit, serves no routes, and Notifications needs its email
    # binding (Step 5). Organizations comes next: registration order matches the
    # order today's routers include them in, so both OpenAPI documents keep their
    # path and tag order (plan 16, "The registry"). It also reads in dependency
    # order: Notifications needs Organizations.
    assert [unit.NAME for unit in UNITS] == ["shared", "organizations", "notifications"]


def test_the_registered_units_subscribe_todays_web_handlers() -> None:
    # Exactly the handler registry CoreProvider writes by hand today
    # (src/app/base/main/ioc/core.py, provide_handler_registry).
    assert collect_subscriptions(unit.WEB_SUBSCRIPTIONS for unit in UNITS) == {
        UserRegisteredEvent: (SendWelcomeEmail,),
        OrganizationInvitationCreatedEvent: (SendOrganizationInvitationEmail,),
    }


def test_the_registered_units_subscribe_todays_cli_handlers() -> None:
    # Exactly the handler registry CliProvider writes by hand today: the CLI
    # creates users, so only the welcome email.
    assert collect_subscriptions(unit.CLI_SUBSCRIPTIONS for unit in UNITS) == {
        UserRegisteredEvent: (SendWelcomeEmail,),
    }


# Two empty providers standing in for two units' providers at one entrypoint.
class FirstUnitsProvider(Provider):
    pass


class SecondUnitsProvider(Provider):
    pass


def test_collect_providers_builds_each_units_providers_in_registration_order() -> None:
    # One fresh instance of every provider class, in registration order: dishka
    # lets a later provider replace an earlier one's binding of the same type,
    # so the order must be exactly the registry's, never shuffled.
    providers = collect_providers([(FirstUnitsProvider,), (SecondUnitsProvider,)])

    assert [type(provider) for provider in providers] == [FirstUnitsProvider, SecondUnitsProvider]


def test_collect_providers_with_no_units_is_empty() -> None:
    # No units registered: each entrypoint keeps only base's own providers.
    assert collect_providers([]) == ()


def test_collect_routers_keeps_every_units_routers_in_registration_order() -> None:
    # Every unit's routers in one list: units in registration order, and each
    # unit's routers in the order it lists them. The order is the include order,
    # which sets the order of paths and tags in the OpenAPI document (plan 16,
    # "The registry"), so it must be exactly the registry's, never shuffled.
    first, second, third = APIRouter(prefix="/first"), APIRouter(prefix="/second"), APIRouter(prefix="/third")

    assert collect_routers([(first, second), (third,)]) == (first, second, third)


def test_collect_routers_with_no_units_is_empty() -> None:
    # No units registered (or none with routes): the app serves only base's own routes.
    assert collect_routers([]) == ()


# Three stand-ins for units' table-mapping functions. Never called: the
# registry only collects them; map_tables() calls them.
def _map_first_table() -> None: ...


def _map_second_table() -> None: ...


def _map_third_table() -> None: ...


def test_collect_table_mappings_keeps_every_units_mappings_in_registration_order() -> None:
    # Every unit's table-mapping functions in one list: units in registration
    # order, each unit's functions in the order it lists them. map_tables() calls
    # them in this order, after base's own tables, so the tables are mapped in
    # exactly today's order (the characterisation test test_mapped_tables pins it).
    assert collect_table_mappings([(_map_first_table, _map_second_table), (_map_third_table,)]) == (
        _map_first_table,
        _map_second_table,
        _map_third_table,
    )


def test_collect_table_mappings_with_no_units_is_empty() -> None:
    # No units registered: map_tables() maps only base's own tables.
    assert collect_table_mappings([]) == ()


# Three stand-ins for units' seed functions. Never called: the registry only
# collects them; scripts/seed_db.py calls them.
async def _seed_first(
    *, session: AsyncSession, user_ids_by_username: Mapping[str, UserId], container: AsyncContainer
) -> None: ...


async def _seed_second(
    *, session: AsyncSession, user_ids_by_username: Mapping[str, UserId], container: AsyncContainer
) -> None: ...


async def _seed_third(
    *, session: AsyncSession, user_ids_by_username: Mapping[str, UserId], container: AsyncContainer
) -> None: ...


def test_collect_seeds_keeps_every_units_seeds_in_registration_order() -> None:
    # Every unit's seed functions in one list: units in registration order, each
    # unit's functions in the order it lists them. seed_db.py runs them in this
    # order, after base's own users and API keys. The registry lists a unit after
    # the units it needs, so a unit's seeds find their data already there.
    assert collect_seeds([(_seed_first, _seed_second), (_seed_third,)]) == (
        _seed_first,
        _seed_second,
        _seed_third,
    )


def test_collect_seeds_with_no_units_is_empty() -> None:
    # No units registered: seed_db.py seeds only base's own users and API keys.
    assert collect_seeds([]) == ()


def test_the_registered_units_supply_todays_web_routers() -> None:
    # Exactly the module router make_v1_router includes by hand today
    # (src/app/base/inbound/http/api_v1_router.py): Organizations' private
    # routes, under the prefix and tag both OpenAPI documents show.
    # Notifications only reacts to events, so it serves no routes.
    routers = collect_routers(unit.make_web_routers(cookie_name="session") for unit in UNITS)

    assert [(router.prefix, router.tags) for router in routers] == [("/organizations", ["Organizations"])]


def test_the_registered_units_supply_todays_public_routers() -> None:
    # Exactly the module router make_public_router includes by hand today
    # (src/app/base/inbound/http/public_api/router.py): Organizations' two
    # read-only routes for API keys. Notifications serves no routes. The paths
    # are read from the OpenAPI document of an app that includes the routers
    # (tests/base/unit/inbound/http/test_api_v1_router.py says why, not
    # router.routes). Exact paths tell the public router apart from the private
    # one, which has the same prefix and tag but many more routes.
    app = FastAPI()
    for router in collect_routers(unit.make_public_routers() for unit in UNITS):
        app.include_router(router)

    assert list(app.openapi()["paths"]) == ["/organizations/", "/organizations/{organization_id}/members/"]


def test_the_registered_units_supply_todays_table_mappings() -> None:
    # Exactly the module mappings map_tables() calls by hand today
    # (src/app/base/outbound/persistence_sqla/mappings/all.py): Organizations'
    # two tables, organizations first, then organization_memberships.
    # Notifications has no tables. The functions are compared by identity: the
    # registry must hand map_tables() these very functions, not copies.
    assert collect_table_mappings(unit.TABLE_MAPPINGS for unit in UNITS) == (
        map_organizations_table,
        map_organization_memberships_table,
    )


def test_the_registered_units_supply_todays_seeds() -> None:
    # Exactly the seeding scripts/seed_db.py does by hand today, beyond base's
    # own users and API keys: Organizations' organizations, memberships and
    # invitations. Notifications stores nothing, so it seeds nothing. Compared
    # by identity: seed_db.py must run this very function.
    assert collect_seeds(unit.SEEDS for unit in UNITS) == (seed_organizations,)


def test_the_registered_units_provide_todays_bindings_at_each_entrypoint() -> None:
    # Each unit's providers at each entrypoint, in registration order: shared
    # binds EmailSender at the three entrypoints that send email
    # (tests/shared/unit/main/ioc/test_providers.py), Organizations binds its
    # ports and use cases in the web app, and its two
    # read-only routes' bindings in the public API
    # (tests/modules/organizations/unit/main/ioc/test_providers.py), and
    # Notifications binds its handlers at the three entrypoints that run them
    # (tests/modules/notifications/unit/main/ioc/test_providers.py).
    assert [type(p) for p in collect_providers(unit.WEB_PROVIDERS for unit in UNITS)] == [
        SharedEmailProvider,
        OrganizationsWebProvider,
        NotificationsWebProvider,
    ]
    assert [type(p) for p in collect_providers(unit.PUBLIC_API_PROVIDERS for unit in UNITS)] == [
        OrganizationsPublicApiProvider,
    ]
    assert [type(p) for p in collect_providers(unit.CLI_PROVIDERS for unit in UNITS)] == [
        SharedEmailProvider,
        NotificationsCliProvider,
    ]
    assert [type(p) for p in collect_providers(unit.WORKER_PROVIDERS for unit in UNITS)] == [
        SharedEmailProvider,
        NotificationsWorkerProvider,
    ]


@pytest.mark.parametrize(
    "get_entrypoint_providers",
    [
        pytest.param(get_providers, id="web"),
        pytest.param(get_cli_providers, id="cli"),
        pytest.param(get_worker_providers, id="worker"),
        pytest.param(get_public_api_providers, id="public_api"),
    ],
)
def test_each_entrypoint_refuses_to_start_when_a_unit_needs_an_unregistered_one(
    get_entrypoint_providers: Callable[[Sequence[Unit]], Iterable[Provider]],
) -> None:
    # Building an entrypoint's providers is the first thing it does at start-up,
    # so refusing here stops the app before it serves anything (plan 16, user
    # story 4), naming which unit needs which.
    units = [FakeUnit(NAME="notifications", NEEDS=("organizations",))]

    with pytest.raises(
        MissingUnitError,
        match=re.escape("Unit 'notifications' needs unit 'organizations', which is not registered."),
    ):
        get_entrypoint_providers(units)


@pytest.mark.parametrize(
    "get_entrypoint_providers",
    [
        pytest.param(get_providers, id="web"),
        pytest.param(get_cli_providers, id="cli"),
        pytest.param(get_worker_providers, id="worker"),
        pytest.param(get_public_api_providers, id="public_api"),
    ],
)
def test_each_entrypoint_refuses_to_start_without_shared(
    get_entrypoint_providers: Callable[[Sequence[Unit]], Iterable[Provider]],
) -> None:
    # The same check at each entrypoint's start-up, with the real Organizations
    # and no shared. One registry list serves every entrypoint, so all four
    # refuse, not only the web app whose error alerting sends the email.
    # Organizations alone, because from Step 5f Notifications needs shared too,
    # and would be named first.
    with pytest.raises(MissingUnitError, match=re.escape("Base needs unit 'shared', which is not registered.")):
        get_entrypoint_providers([organizations])


def _provided_types(providers: Iterable[Provider]) -> set[Any]:
    # What the providers bind: the type each of their factories provides, read
    # from the declarations without building a container.
    return {factory.provides.type_hint for provider in providers for factory in provider.factories}


@pytest.mark.parametrize(
    ("get_entrypoint_providers", "organizations_provider"),
    [
        pytest.param(get_providers, OrganizationsWebProvider, id="web"),
        pytest.param(get_public_api_providers, OrganizationsPublicApiProvider, id="public_api"),
    ],
)
def test_an_entrypoint_built_without_modules_binds_nothing_organizations_binds(
    get_entrypoint_providers: Callable[[Sequence[Unit]], Iterable[Provider]],
    organizations_provider: type[Provider],
) -> None:
    # The feature-delete rule for bindings (plan 16, user story 4): an entrypoint
    # built with no modules registered (only shared, which base needs) binds none
    # of Organizations' ports or use cases, so deregistering Organizations removes
    # every one of them. Compared with what Organizations' own provider binds, so
    # the two can't drift apart.
    without_modules = _provided_types(get_entrypoint_providers((shared,)))

    assert without_modules & _provided_types([organizations_provider()]) == set()


@pytest.mark.parametrize(
    "get_entrypoint_providers",
    [
        pytest.param(get_providers, id="web"),
        pytest.param(get_cli_providers, id="cli"),
        pytest.param(get_worker_providers, id="worker"),
    ],
)
def test_an_entrypoint_built_without_modules_binds_email_only_through_shared(
    get_entrypoint_providers: Callable[[Sequence[Unit]], Iterable[Provider]],
) -> None:
    # Email's binding lives in shared (plan 16, Step 5): of every provider the
    # entrypoint is built from, only SharedEmailProvider binds what it binds, so
    # the adapter is chosen in one place, not in three copies (CoreProvider,
    # CliProvider and WorkerProvider before Step 5). The public API isn't here:
    # it sends no email.
    shareds = _provided_types([SharedEmailProvider()])
    binders = [type(p) for p in get_entrypoint_providers((shared,)) if _provided_types([p]) & shareds]

    assert binders == [SharedEmailProvider]


# The pub/sub registry an entrypoint's event dispatcher reads (provide_handler_registry
# in CoreProvider and CliProvider): each event type, and the handlers it is delivered to.
HandlerRegistry = dict[type[DomainEvent], Sequence[EventHandler[Any]]]


@pytest.mark.parametrize(
    "get_entrypoint_providers",
    [
        pytest.param(get_providers, id="web"),
        pytest.param(get_cli_providers, id="cli"),
    ],
)
async def test_an_entrypoint_built_without_modules_subscribes_no_handlers(
    get_entrypoint_providers: Callable[[Sequence[Unit]], Iterable[Provider]],
) -> None:
    # The feature-delete rule at unit speed (plan 16, user story 4): an entrypoint
    # built with no modules registered (only shared, which base needs, and
    # subscribes nothing; Notifications removed) subscribes none of their
    # handlers. If it subscribed one, the registry would ask dishka for a
    # handler nobody bound, and the first command that raises an event would fail
    # with NoFactoryError. tests/base/integration/with_infra/main/
    # test_app_without_notifications.py proves the same end to end for the web app.
    # The worker isn't here: it has no registry, it resolves each handler by its
    # dotted path. No settings are passed in: the registry needs only the container
    # itself, and building a container or a scope never opens a connection.
    # skip_validation: dishka normally checks the whole graph at build time, which
    # needs every settings object the real entrypoint passes in (PasswordHasherSettings
    # and the rest). Only the registry is resolved here, so dishka checks just what it
    # needs. Each real entrypoint's whole graph is still validated by
    # tests/base/characterisation/main/test_container_bindings.py and the integration tests.
    container = make_async_container(*get_entrypoint_providers((shared,)), skip_validation=True)
    try:
        # REQUEST scope, as a real request or CLI command resolves it.
        async with container() as request_container:
            registry = await request_container.get(HandlerRegistry)
    finally:
        await container.close()

    assert registry == {}
