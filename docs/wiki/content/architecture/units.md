# Units: base, Modules and shared

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/base/main/modules.py`](../../../../src/app/base/main/modules.py) — the registry: the `Unit` Protocol, `UNITS`, `BASE_NEEDS`, and the start-up "needs" check
    - [`src/app/modules/organizations/main/module.py`](../../../../src/app/modules/organizations/main/module.py), [`src/app/modules/notifications/main/module.py`](../../../../src/app/modules/notifications/main/module.py), [`src/app/shared/main/module.py`](../../../../src/app/shared/main/module.py) — how each unit plugs in
    - [`src/app/modules/organizations/core/api.py`](../../../../src/app/modules/organizations/core/api.py) — the only part of Organizations another module may import
    - [`pyproject.toml`](../../../../pyproject.toml) — the `[[tool.importlinter.contracts]]` that keep the units apart
    - [`tests/modules/`](../../../../tests/modules/) and [`tests/shared/`](../../../../tests/shared/) — each unit's own tests, mirroring its code
    - [`docs/plans/16-modular-monolith.md`](../../../../docs/plans/16-modular-monolith.md) — the plan that introduced units, with every decision behind them

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What a unit is

The app is one deployable process (a **modular monolith**), split into **units** that each own their code, their tests and their place in the import rules. There are three kinds:

- **`base`** (`src/app/base/`) — the original author's app, unchanged below the prefix: accounts, sessions, users, API keys, the CLI, the worker, and the **composition root** (`base/main/`), the one place that registers every other unit.
- **A module** (`src/app/modules/<name>/`) — one bounded context (see [Outbound Layer](outbound-layer.md) for the term), removable without touching the rest. Today: **Organizations** and **Notifications**.
- **`shared`** (`src/app/shared/`) — domain-free building blocks with no business meaning, such as the email adapters. Only `base/main` imports it.

## The real unit graph

Generated from the code by [`scripts/wiki/dependency_graph.py`](../../../../scripts/wiki/dependency_graph.py), the same way as the layer graph on [Layer Dependencies & Import Rules](layer-dependencies.md):

{% include-markdown "../../generated/unit-graph.md" %}

## The same four layers inside every unit

Every unit keeps the four layers `base` has (`main`, `inbound`, `outbound`, `core`), with the same import rule inside it (see [Layer Dependencies & Import Rules](layer-dependencies.md)). A unit has only the layers it needs. Today's tree, under [`src/app/`](../../../../src/app/):

```text
src/app/
├── base/                  the original app
│   ├── main/              the composition root: the registry, every entrypoint, every container
│   ├── inbound/
│   ├── outbound/
│   └── core/
├── modules/
│   ├── organizations/     a bounded context
│   │   ├── main/          module.py, ioc/, config/, seed.py
│   │   ├── inbound/
│   │   ├── outbound/
│   │   └── core/          api.py: what other modules may import
│   └── notifications/
│       ├── main/
│       └── core/
└── shared/                domain-free building blocks
    ├── main/
    └── outbound/
```

Tests mirror the code: `tests/base/`, `tests/modules/<name>/`, `tests/shared/`.

## How a unit plugs in

A unit is its `main/module.py`. It defines a fixed set of names at module level, and the registry in [`src/app/base/main/modules.py`](../../../../src/app/base/main/modules.py) reads them for every unit in `UNITS`, in order. A unit never imports `base/main` (an import rule forbids it), so nothing in a unit knows about the registry; mypy checks each registered unit against the registry's `Unit` Protocol instead. Every unit defines every name, empty where it has nothing to give:

- `NAME`, and `NEEDS`: the units it needs at run time, whether or not it imports them.
- `WEB_SUBSCRIPTIONS`, `CLI_SUBSCRIPTIONS`: which of its event handlers handle which events, at the two entrypoints that dispatch events.
- `WEB_PROVIDERS`, `PUBLIC_API_PROVIDERS`, `CLI_PROVIDERS`, `WORKER_PROVIDERS`: its Dishka providers at each entrypoint (see [Dependency Injection with Dishka](../core-patterns/dependency-injection.md)).
- `TABLE_MAPPINGS`: its table-mapping functions, which `map_tables()` runs after `base`'s own.
- `SEEDS`: its development-data seed functions, which `scripts/seed_db.py` runs after `base`'s users and API keys.
- `make_web_routers(*, cookie_name)`, `make_public_routers()`: its routers under `/api/v1` and `/public/v1`.

Notifications is the smallest worked example. An excerpt from [`src/app/modules/notifications/main/module.py`](../../../../src/app/modules/notifications/main/module.py):

```python
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
```

`UNITS = (shared, organizations, notifications)` lists each unit after the units it needs, so their providers, routers, mappings and seeds come after the things they build on.

## The rules, and who enforces them

Seven `import-linter` contracts in [`pyproject.toml`](../../../../pyproject.toml) keep the units apart. They run in `make check`, and each is tested against a fake violation in `tests/base/unit/architecture/test_import_contracts.py`:

- **`unit-order`** — `base/main` sits above every unit, and `base`'s other layers below them: the composition root may import any unit, but `base`'s `inbound`, `outbound` and `core` never import one, and no unit imports `base/main`.
- **`unit-layers`** — every module, and `shared`, keeps the four layers inside, in the same order; any other folder directly inside a module is an error.
- **`module-order`** — modules depend on each other one way only (Notifications may use Organizations, never the reverse). It lists every module, so a new one has to be placed on purpose.
- **`module-core-uses-base-core-only`** — a module's `core` imports only `base`'s `core` (ports, events, entities), never its adapters or routes.
- **`outbound-not-base-inbound`** — a module's `outbound`, and all of `shared`, never import `base`'s `inbound`.
- **`organizations-internals`** — other modules may import only Organizations' [`core/api.py`](../../../../src/app/modules/organizations/core/api.py).
- **`shared-internals`** — only `base/main` imports `shared`.

The four CQRS contracts also cover every module's `core` (see [Layer Dependencies & Import Rules](layer-dependencies.md#the-cqrs-split-and-the-auth-ctx-boundary)).

**What the contracts can't see** is a need that isn't an import: Notifications needs `shared`'s email binding at run time but imports only `base`'s `EmailSender` port. That's what `NEEDS` is for. Every entrypoint runs the registry's [`check_needs()`](../../../../src/app/base/main/modules.py) before building anything, and refuses to start when a registered unit needs one that isn't registered, naming both:

```text
MissingUnitError: Unit 'notifications' needs unit 'organizations', which is not registered.
```

`base`'s own need (`shared`, for the error alerting's email) is `BASE_NEEDS`, in the registry itself.

## Removing a module

Take it out of `UNITS`. Its routes, bindings, subscriptions and seeds go with it; the rest of the app starts and works (`tests/base/integration/with_infra/main/test_app_without_notifications.py` proves it for Notifications). If another registered unit needs it, every entrypoint refuses to start and says which one. Its tables and migrations stay: there is one Alembic history for every unit (see [Database Migrations](../development-guide/database-migrations.md)).

## Adding a module, step by step

Every step is test-first ([TDD](../testing/tdd.md)): a test that fails for the right reason, then the code that makes it pass.

1. **Create `src/app/modules/<name>/`** with only the layers it needs (`core/`, `inbound/`, `outbound/`, `main/`), each a package.
2. **Write `main/module.py`**, defining every name above. Copy Notifications' or Organizations' and empty what you don't use.
3. **Register it** in `UNITS` in `src/app/base/main/modules.py`, after the units it needs. `tests/base/unit/main/test_modules.py` pins the registry's order, so update that test first.
4. **Place it in `module-order`** in `pyproject.toml`, above the modules it uses and below those that use it. If other modules will import it, give it a `core/api.py` and a `protected` contract like `organizations-internals`. The import-contract tests check that every registered module is a required layer of `module-order`.
5. **Tables:** mapping functions in its `outbound/persistence_sqla/mappings/`, listed in `TABLE_MAPPINGS`, then `make migration msg="…"` (see [Database Migrations](../development-guide/database-migrations.md)).
6. **Tests:** under `tests/modules/<name>/`, mirroring the code. The `Makefile` picks them up by folder, with no edit. Infrastructure tests get a `conftest.py` that imports the `base` fixtures they use, as Organizations' does.
7. **Characterisation tests:** new routes or bindings change the committed OpenAPI snapshots and the containers' pinned bindings under `tests/base/characterisation/`, on purpose; update them in their own reviewed step.
8. **Run** `make check unit=<name>` while working, and the full `make check` and `make test-docker` before committing.

## Testing one unit

`unit=<name>` narrows `make check` or `make test-docker` to one unit's tests. See [Running Tests → One unit's tests](../testing/running-tests.md#one-units-tests-unit).

## Where to go next

- [Layer Dependencies & Import Rules](layer-dependencies.md) — the four layers every unit keeps, and the contracts behind them.
- [Main (Composition Root)](main-composition-root.md) — where the registry's units become containers and apps.
- [Organizations (Multi-Tenancy)](../core-patterns/organizations.md) — the largest module, end to end.
