"""
Tests for today's import-linter contracts (docs/plans/16-modular-monolith.md, Step 1).

`lint-imports` in `make check` proves the code keeps every contract in pyproject.toml,
but not that a contract would catch a forbidden import: a contract whose module names
match nothing in the code is kept just as quietly. Step 2 renames every contract's
modules (`app.` -> `app.base.`), so these tests prove each contract still catches what
it should. They read the contracts from pyproject.toml, so the rules live in one place,
and check them with import-linter's own contract classes, the same code `lint-imports`
runs. Confirmation tests: they pass on their first run; every contract added from
Step 2 on comes RED first.
"""

import copy
from typing import Any

import grimp
import pytest
from importlinter.api import read_configuration
from importlinter.contracts.forbidden import ForbiddenContract
from importlinter.contracts.layers import LayersContract
from importlinter.contracts.protected import ProtectedContract
from importlinter.domain.contract import Contract

from app.base.main.modules import UNITS

# The contract types pyproject.toml uses today. A new type is added here together
# with the first contract that uses it.
_CONTRACT_CLASSES: dict[str, type[Contract]] = {
    "layers": LayersContract,
    "forbidden": ForbiddenContract,
    "protected": ProtectedContract,
}

# (importer, imported) pairs that every contract allows. The module names are real; the
# imports are examples of each allowed kind, not a copy of the real graph.
ALLOWED_IMPORTS: list[tuple[str, str]] = [
    # main -> inbound, inbound -> core (skipping outbound), outbound -> core
    ("app.base.main.run", "app.base.inbound.http.root_router"),
    ("app.base.inbound.http.users.list_users", "app.base.core.queries.list_users"),
    ("app.base.outbound.adapters.sqla_user_finder", "app.base.core.common.ports.user_finder"),
    ("app.base.outbound.auth_ctx.service", "app.base.core.common.entities.user"),
    # commands and queries may import common, and their own kind
    ("app.base.core.commands.create_user", "app.base.core.common.services.user"),
    ("app.base.core.queries.list_users", "app.base.core.queries.ports.user_reader"),
    # The three exceptions clean-architecture's ignore_imports lists. import-linter reports
    # an ignored import missing from the graph as an error, so they have to be here, and
    # the contract staying kept with them proves the exceptions still apply.
    ("app.base.outbound.persistence_sqla.alembic.env", "app.base.main.config.loader"),
    ("app.base.outbound.persistence_sqla.alembic.env", "app.base.main.config.settings"),
    ("app.base.outbound.persistence_sqla.alembic.env", "app.base.main.modules"),
    # Inside a module, the same layers (main -> core); across the boundary, a
    # module's core -> base's core.
    (
        "app.modules.notifications.main.module",
        "app.modules.notifications.core.common.events.handlers.send_welcome_email",
    ),
    (
        "app.modules.notifications.core.common.events.handlers.send_welcome_email",
        "app.base.core.common.ports.email_sender",
    ),
    # Between modules, one way only: Notifications uses Organizations' public API
    # (what Step 4 makes real for the invitation event).
    (
        "app.modules.notifications.core.common.events.handlers.send_organization_invitation_email",
        "app.modules.organizations.core.api",
    ),
    # A module's outbound may use base's outbound: Organizations' reader joins base's
    # users table (what Step 4 brings in).
    (
        "app.modules.organizations.outbound.adapters.sqla_organization_reader",
        "app.base.outbound.persistence_sqla.mappings.user",
    ),
    # Organizations' internals, imported from inside the module or by base's main/, the
    # composition root (import rule 5). Together they put every protected package in the
    # fake graph, so organizations-internals checks each one.
    ("app.base.main.modules", "app.modules.organizations.main.module"),
    (
        "app.modules.organizations.inbound.http.private_api.create_organization",
        "app.modules.organizations.core.commands.create_organization",
    ),
    (
        "app.modules.organizations.outbound.adapters.sqla_organization_reader",
        "app.modules.organizations.core.queries.ports.organization_reader",
    ),
    (
        "app.modules.organizations.core.api",
        "app.modules.organizations.core.common.events.organization_invitation_created",
    ),
    # shared, imported only by base's main/, the composition root (import rule 5), and its own
    # packages importing each other, which a protected contract always allows. Together they
    # put shared in the fake graph, so shared-internals checks it.
    ("app.base.main.modules", "app.shared.main.module"),
    ("app.shared.main.module", "app.shared.main.ioc.providers"),
]

# Contract id -> the forbidden imports it must catch. Each is added to ALLOWED_IMPORTS on its
# own and must break the contract by itself. A contract that spans several units lists one
# import per side it covers (base's, a module's own, across the boundary), so every side is
# proven, not just the first.
FORBIDDEN_IMPORTS: dict[str, list[tuple[str, str]]] = {
    # base's lower layers importing a module: what mappings/all.py would do if it named
    # Organizations' mappings directly once they move (Step 4 takes them from the registry)
    "unit-order": [
        (
            "app.base.outbound.persistence_sqla.mappings.all",
            "app.modules.organizations.outbound.persistence_sqla.mappings.organization",
        ),
    ],
    # core importing outward
    "clean-architecture": [("app.base.core.commands.create_user", "app.base.outbound.adapters.sqla_user_reader")],
    # a module's core importing its own main (its composition): inward code reaching outward
    "unit-layers": [
        (
            "app.modules.notifications.core.common.events.handlers.send_welcome_email",
            "app.modules.notifications.main.module",
        ),
        # shared, which keeps a module's layers too (Step 5): its SMTP adapter reading shared's
        # email settings itself, instead of being given them by shared's provider
        ("app.shared.outbound.adapters.smtp_email_sender", "app.shared.main.config.settings"),
    ],
    # a lower module importing a higher one: Organizations calling Notifications' email
    # handler directly instead of raising its event
    "module-order": [
        (
            "app.modules.organizations.core.commands.invite_organization_member",
            "app.modules.notifications.core.common.events.handlers.send_organization_invitation_email",
        ),
    ],
    # a module's core importing base's outer layers: Notifications' welcome-email handler
    # looking a user up through a concrete database adapter instead of base's UserFinder port
    "module-core-uses-base-core-only": [
        (
            "app.modules.notifications.core.common.events.handlers.send_welcome_email",
            "app.base.outbound.adapters.sqla_user_finder",
        ),
    ],
    # a module's outbound importing base's inbound: an Organizations adapter reaching
    # into base's HTTP middleware
    "outbound-not-base-inbound": [
        (
            "app.modules.organizations.outbound.adapters.sqla_organization_reader",
            "app.base.inbound.http.auth_cookie_middleware",
        ),
        # shared, any layer of it, importing base's inbound: its email provider reaching into
        # base's error alerting (unit-order allows this: shared sits above base's inbound)
        ("app.shared.main.ioc.providers", "app.base.inbound.http.errors.alerting"),
    ],
    # another module importing Organizations' internals: Notifications' invitation-email
    # handler importing the event from its own file instead of from core/api.py
    "organizations-internals": [
        (
            "app.modules.notifications.core.common.events.handlers.send_organization_invitation_email",
            "app.modules.organizations.core.common.events.organization_invitation_created",
        ),
    ],
    # anything but base's main/ importing shared: a module (Notifications' providers binding
    # email again with shared's provider, instead of the registry binding it once), and base's
    # other layers (its error alerting reading shared's email settings directly)
    "shared-internals": [
        ("app.modules.notifications.main.ioc.providers", "app.shared.main.ioc.providers"),
        ("app.base.inbound.http.errors.exception_middleware", "app.shared.main.config.settings"),
    ],
    "cqrs-common-must-not-import-commands": [
        (
            "app.base.core.common.services.user",
            "app.base.core.commands.create_user",
        ),
        # a module's common importing its own command
        (
            "app.modules.organizations.core.common.entities.organization",
            "app.modules.organizations.core.commands.create_organization",
        ),
        # a module's common importing base's command, across the boundary
        ("app.modules.organizations.core.common.entities.organization", "app.base.core.commands.create_user"),
    ],
    "cqrs-common-must-not-import-queries": [
        ("app.base.core.common.services.user", "app.base.core.queries.list_users"),
        # a module's common importing its own query
        (
            "app.modules.organizations.core.common.entities.organization",
            "app.modules.organizations.core.queries.list_my_organizations",
        ),
        # a module's common importing base's query, across the boundary
        ("app.modules.organizations.core.common.entities.organization", "app.base.core.queries.list_users"),
    ],
    "cqrs-commands-must-not-import-queries": [
        ("app.base.core.commands.create_user", "app.base.core.queries.list_users"),
        # a module's command importing its own query
        (
            "app.modules.organizations.core.commands.create_organization",
            "app.modules.organizations.core.queries.list_my_organizations",
        ),
        # a module's command importing base's query, across the boundary
        ("app.modules.organizations.core.commands.create_organization", "app.base.core.queries.list_users"),
    ],
    "cqrs-queries-must-not-import-commands": [
        ("app.base.core.queries.list_users", "app.base.core.commands.create_user"),
        # a module's query importing its own command
        (
            "app.modules.organizations.core.queries.list_my_organizations",
            "app.modules.organizations.core.commands.create_organization",
        ),
        # a module's query importing base's command, across the boundary
        ("app.modules.organizations.core.queries.list_my_organizations", "app.base.core.commands.create_user"),
    ],
    # auth_ctx using the app's adapters instead of its own
    "auth-ctx": [("app.base.outbound.auth_ctx.service", "app.base.outbound.adapters.sqla_user_finder")],
}

# Every (contract id, forbidden import) pair, so each forbidden import gets its own test and a
# failure names the contract and the import's position in its list (unit-order-1, ...).
_FORBIDDEN_CASES = [
    pytest.param(contract_id, forbidden_import, id=f"{contract_id}-{position}")
    for contract_id, forbidden_imports in FORBIDDEN_IMPORTS.items()
    for position, forbidden_import in enumerate(forbidden_imports, start=1)
]


def _contract(contract_id: str) -> Contract:
    # read_configuration() reads pyproject.toml from the working directory, as
    # `lint-imports` does; make check and make test-docker both run from the
    # repository root.
    configuration = read_configuration()
    options_by_id = {options["id"]: options for options in configuration["contracts_options"]}
    options = options_by_id[contract_id]
    return _CONTRACT_CLASSES[options["type"]](
        name=options["name"],
        session_options=configuration["session_options"],
        contract_options=options,
    )


def _fake_graph(imports: list[tuple[str, str]]) -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    for importer, imported in imports:
        for module in (importer, imported):
            # Every package above a module goes in too ("app", "app.base.core", ...): the
            # contracts name packages, and a package missing from the graph is an
            # error or is skipped, never a real check.
            parts = module.split(".")
            for end in range(1, len(parts) + 1):
                name = ".".join(parts[:end])
                if name not in graph.modules:
                    graph.add_module(name)
        graph.add_import(importer=importer, imported=imported)
    return graph


@pytest.fixture(scope="module")
def real_graph() -> grimp.ImportGraph:
    # Built once for the module, with the same scan settings as `lint-imports`.
    # pyproject.toml's booleans arrive as strings ("True"), as import-linter reads them.
    # cache_dir=None: no .grimp_cache is written, which would fail in the test
    # container (see build_app_graph() in scripts/wiki/dependency_graph.py).
    session_options: dict[str, Any] = read_configuration()["session_options"]
    return grimp.build_graph(
        *session_options["root_packages"],
        exclude_type_checking_imports=session_options["exclude_type_checking_imports"] == "True",
        cache_dir=None,
    )


def test_every_contract_in_pyproject_has_a_forbidden_import_here() -> None:
    # A contract added to pyproject.toml without a forbidden import above fails here,
    # so no contract goes unproven.
    contract_ids = {options["id"] for options in read_configuration()["contracts_options"]}

    assert contract_ids == set(FORBIDDEN_IMPORTS)


@pytest.mark.parametrize("contract_id", list(FORBIDDEN_IMPORTS))
def test_the_real_code_keeps_the_contract(contract_id: str, real_graph: grimp.ImportGraph) -> None:
    # A contract removes its ignored imports from the graph it checks, so each check
    # gets its own copy, as `lint-imports` does.
    check = _contract(contract_id).check(copy.deepcopy(real_graph), verbose=False)

    assert check.kept


@pytest.mark.parametrize(("contract_id", "forbidden_import"), _FORBIDDEN_CASES)
def test_one_forbidden_import_breaks_the_contract(contract_id: str, forbidden_import: tuple[str, str]) -> None:
    contract = _contract(contract_id)

    # Kept with only allowed imports, broken once this one forbidden import is added:
    # that import, and nothing else, is what the contract catches.
    assert contract.check(_fake_graph(ALLOWED_IMPORTS), verbose=False).kept
    assert not contract.check(_fake_graph([*ALLOWED_IMPORTS, forbidden_import]), verbose=False).kept


def test_every_registered_module_is_a_required_layer_in_module_order() -> None:
    # module-order lists the modules in their one allowed direction (plan 16, import
    # rule 3). A layer in parentheses is optional: import-linter skips it when the
    # package doesn't exist, which suited a module before it was registered. Once a
    # module is in the registry it must be a required layer, so renaming or deleting
    # its package breaks the contract instead of passing quietly (plan 16, "no unit
    # is left out"). shared is a unit but not a module, so it is left out here: its
    # own contracts guard it (Step 5).
    contracts = {options["id"]: options for options in read_configuration()["contracts_options"]}

    assert {unit.NAME for unit in UNITS if unit.NAME != "shared"} <= set(contracts["module-order"]["layers"])


def test_shared_is_a_required_layer_in_unit_order() -> None:
    # unit-order places shared between the modules and base's lower layers (plan 16,
    # import rule 1). A layer in parentheses is optional: import-linter skips it when the
    # package doesn't exist, which suited shared before Step 5 made it a package. shared
    # is now registered and base needs it, so it must be a required layer: renaming or
    # deleting src/app/shared/ then breaks the contract instead of passing quietly.
    contracts = {options["id"]: options for options in read_configuration()["contracts_options"]}

    assert "app.shared" in contracts["unit-order"]["layers"]


def test_modules_is_a_required_layer_in_unit_order() -> None:
    # unit-order places the modules between base's main/ and shared (plan 16, import
    # rule 1). A layer in parentheses is optional: import-linter skips it when the
    # package doesn't exist, which suited app.modules before Step 3 made it a package.
    # Organizations and Notifications now live there and are registered, so it must be
    # a required layer: renaming or deleting src/app/modules/ then breaks the contract
    # instead of passing quietly.
    contracts = {options["id"]: options for options in read_configuration()["contracts_options"]}

    assert "app.modules" in contracts["unit-order"]["layers"]
