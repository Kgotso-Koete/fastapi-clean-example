# 16. Modular monolith: one registrable module per bounded context

> **Status: researched, not started** (research done 2026-10-17; this plan rewritten from it). **Sequencing:** this restructuring comes before search and file storage (`docs/plans/11-search.md`, `docs/plans/12-file-storage.md`), which are then built straight into modules (decided by the human maintainer, 2026-10-17; recorded in `docs/plans/0-production-readiness-roadmap.md`). It was to follow plan 14 (`docs/plans/14-row-level-security.md`), which was parked on 2026-10-21 and no longer comes first. Rough size: about 3 weeks of working days.
>
> **Ground rules for this plan** (human maintainer, 2026-10-17):
> - **The one exception to the original-author rule.** This restructuring is the only time this codebase makes major changes to the original author's code. The exact terms are in `docs/plans/agents.md` 3.1: files are relocated, never rewritten; the hand-written composition (DI providers, routers, table mappings) may change so the app is built from a registry of modules; nothing else.
> - **A clean bill of health first.** It starts from a released commit with nothing uncommitted and nothing half-done. Every known behaviour is the same afterwards, including the known open issues listed in the roadmap (they are fixed separately, never during this plan).
> - **TDD for every piece of new code** the restructuring needs (the registry, the module contracts, the wiki generator changes). Only pure moves are exempt, and they are proven by unchanged test counts and characterisation tests instead (Step 0).
> - **`make check` and `make test-docker` still run every unit and every integration test.** New commands run one module's tests on their own.

## Goal

Reorganize this codebase from today's layer-first structure (`core/`, `inbound/`, `outbound/`, each holding every bounded context's files side by side) into a **modular monolith**: one folder per bounded context, each following this repo's DDD/Clean Architecture/Hexagonal/CQRS conventions inside. It stays one codebase, one database and one Alembic history. The composition roots in `main/` build the app from **one registry of modules** instead of naming every router, provider and mapping by hand. A module that nothing else depends on (Notifications today, a fork's own business module later) can be deregistered by removing it from the registry, and the rest of the app still starts and passes its tests.

The point: a fork's own large domains each become a module from day one, with boundaries enforced by `lint-imports` in `make check`, instead of more files added to shared layer folders.

## User stories

Not user-facing: no route, response or behaviour changes. These are for developers of this template and its forks.

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. One place per domain | developer on a fork | all of one bounded context's code in one folder | I can understand and change a domain without hunting across layer folders | Each module holds its own `core/`, `inbound/` and `outbound/`, and its tests mirror it<br>A new business domain is added as a new module |
| 2. Enforced boundaries | maintainer | modules to use each other only through a small public API, in one direction | a shortcut import can't quietly couple two domains | `make check` fails if a module imports another module's internals<br>Module dependencies run one way only (Organizations → Identity, never back)<br>The layers contract holds inside every module |
| 3. One registry | developer on a fork | to register a module in exactly one place | nothing drifts out of step | The web app, the public API, the CLI and the worker all build their wiring from the same registry<br>Routers, providers, table mappings, event handlers, CLI commands and constraint-error mappings all come from it |
| 4. Removable modules | developer on a fork | to remove a module nothing depends on, by removing one registry entry | a template feature I don't need can be dropped cleanly | With Notifications removed, the app starts, sign-up still succeeds and no email is sent<br>A module whose dependency is missing from the registry refuses to start, naming the missing module |
| 5. Tests per module | developer | to run one module's unit or integration tests on their own | I get fast feedback on the module I'm changing | `make check` and `make test-docker` still run everything<br>A per-module command runs exactly that module's tests |
| 6. Nothing changes for users | API client | every route to behave exactly as before | the restructuring is invisible | Both OpenAPI documents are identical before and after<br>The same test counts pass before and after every move step |

## What the research found

Studied 2026-10-17. **Local copies, for re-reading:** `ai_research/16-modular-monolith/` at the repository root (git-ignored, so only on the machine that downloaded it): `repos/` (13 cloned repositories), `web/` and `text/` (17 articles and docs pages; the text made with `ai_research/tools/to_text.py`), and `notes/` (one findings note per group of sources, with file paths). If the folder is missing, rebuild it from the URLs below. Trust signals checked on GitHub the same day.

**The references** (per `docs/plans/agents.md` 6.2):

| Repository | Stars / forks / contributors | Created | What it contributed |
|---|---|---|---|
| https://github.com/kgrzybek/modular-monolith-with-ddd | 14.1k / 2.2k / 33 | 2019 | The canonical reference; the module shape, events between modules, and its failures (below) |
| https://github.com/spring-projects/spring-modulith | 1.2k / 228 / 95 | 2022 | Precise boundary rules, module isolation tests, and the outbox-style event publication registry |
| https://github.com/Shopify/packwerk (+ three Shopify engineering articles) | 1.9k / 123 / 83 | 2020 | What went wrong enforcing boundaries at scale |
| https://github.com/ddd-by-examples/library | 5.9k / 833 / 22 | 2019 | Choosing contexts, one-way integration by events, direction-only architecture tests |
| https://github.com/ThreeDotsLabs/wild-workouts-go-ddd-example | 6.5k / 589 / 13 | 2020 | Consumer-owned ports, one composition function per context |
| https://github.com/Sairyss/domain-driven-hexagon | 15.0k / 1.6k / 20 | 2020 | Module rules in prose, and their breakage in its own code |
| https://github.com/evolutionary-architecture/evolutionary-architecture-by-example | 3.6k / 541 / 9 | 2023 | A module registry with per-module enabled flags |
| https://github.com/pgorecki/python-ddd and https://github.com/pgorecki/lato | 1.0k / 127 / 3; 216 / 7 / 2 | 2018; 2023 | Python modular monolith: explicit module list, events in one transaction |
| https://github.com/cosmicpython/code | 2.7k / 1.1k / 6 | 2019 | The Python reference for the patterns this repo already uses |
| https://github.com/arctikant/fastapi-modular-monolith-starter-kit | 55 / 12 / 1 | 2024 | The "gateway" facade (`app/auth/gateway.py`), recommended by the human maintainer |
| https://github.com/Khaled-Farhat/modular-monolith-practice | 2 / 1 / 1 | 2026 | The cleanest cross-module call pattern found, recommended by the human maintainer (weak trust signal) |
| https://github.com/seddonym/import-linter | 1.2k / 89 | 2019 | The boundary checker this repo already uses (pinned at 2.15) |

Articles: Kamil Grzybek's modular monolith series (https://www.kamilgrzybek.com/blog/posts/modular-monolith-primer and its four sequels), Shopify's "Deconstructing the Monolith" (https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity), "Under Deconstruction" (https://shopify.engineering/shopify-monolith) and "A Packwerk Retrospective" (https://shopify.engineering/a-packwerk-retrospective), the Spring Modulith reference docs (https://docs.spring.io/spring-modulith/reference/fundamentals.html), Jimmy Bogard on vertical slices (https://www.jimmybogard.com/vertical-slice-architecture/), Martin Fowler's MonolithFirst (https://martinfowler.com/bliki/MonolithFirst.html), and the Alembic branches (https://alembic.sqlalchemy.org/en/latest/branches.html), dishka components (https://dishka.readthedocs.io/en/stable/advanced/components.html) and FastAPI bigger-applications docs (https://fastapi.tiangolo.com/tutorial/bigger-applications/).

**Findings that shaped the design:**

1. **No Python repo has a complete module contract, and none enforces its boundaries with a tool.** None of the five Python repos has one module object bringing its own providers, routers, mappings and handlers, none uses dishka, and none runs import-linter or an equivalent. Every one relied on convention and broke it, even in its own tests (Khaled-Farhat's test fakes import other modules' private `internal` code; python-ddd's bidding module imports `catalog.domain.events`; domain-driven-hexagon's wallet module imports user's event by its internal path, though its README forbids it). So this plan designs the contract itself, and enforcement is automatic from day one.
2. **Register each module in exactly one place, and derive everything from it.** kgrzybek's host lists every module by hand twice (`src/API/.../Startup.cs`), its architecture tests keep their own module lists, and the newest module (Registrations) is missing from both: half-wired, and unchecked. evolutionary-architecture's `ModulesRegistry` and python-ddd's explicit module list are the better shape.
3. **Enforcement must be proven, not assumed.** One of kgrzybek's layer tests checks the wrong project, so its rule never runs. Each boundary rule here gets a deliberate RED: a forbidden import added on purpose, seen failing, then removed.
4. **Dependencies first, privacy second, and keep the public API small.** Shopify removed Packwerk's privacy checks in 3.0: the `app/public` folders filled with "poorly-documented public code that was never meant to be public", and developers designed APIs instead of asking whether the dependency should exist at all. Their debt is "a long way from being paid off". So the first contracts enforce direction; each module's public API starts as exactly what other modules already use today, and is never grown speculatively.
5. **Prove isolation by running code.** Shopify found packages with zero violations that still failed to boot alone. Spring Modulith's `@ApplicationModuleTest` boots one module with the others mocked. Here: the feature-delete test boots the app without Notifications.
6. **Modules integrate one way, through events, with the listener depending on the publisher.** ddd-by-examples (catalogue → lending), Spring Modulith (listeners after commit, an event publication registry that is effectively an outbox), and kgrzybek (outbox and inbox per module). This repo's dispatcher and transactional outbox already do this. kgrzybek's bus throws when an event has no subscriber, which makes removing a module break its publishers; this repo's dispatcher already ignores events nobody handles (`tests/unit/outbound/adapters/test_hybrid_event_dispatcher.py::...test_ignores_events_with_no_registered_handlers`), which is what makes Notifications removable.
7. **Synchronous calls between modules use a facade owned by the provider and a port owned by the consumer.** arctikant's gateway (`app/auth/gateway.py`: an ABC returning DTOs, exported from the module's `__init__`) is the provider side; Khaled-Farhat adds the consumer side: the consumer declares its own port (`orders/internal/core/ports/catalog_gateway_port.py`) and an outbound adapter calls the provider's facade. wild-workouts does the same (`app/command/services.go`). Recorded as the direction for new cross-module calls; today's existing calls stay as they are (Decision 4).
8. **One database and one migration history is normal.** Every Python reference uses one database and one shared metadata; kgrzybek keeps one central migrations folder and one history table even with a schema per module. Per-module Alembic histories are possible (multiple bases, `version_locations`, branch labels, `depends_on`), but the 11 existing linear revisions can't move, every `alembic upgrade head` call would change to `heads`, the stairway test assumes one `down_revision`, autogenerate compares one whole `MetaData`, and the docs warn branching "can get pretty crazy!". So one history stays (see "Things to think about").
9. **Plain per-module dishka providers, not dishka components.** Components isolate resolution, not imports, so import-linter is still the real boundary; every cross-component use would need `FromComponent`, FastAPI's `FromDishka` only reads the default component, and splitting shared providers could give each component its own session inside one request, breaking the single transaction the outbox relies on.
10. **This plan is modules per bounded context, not vertical slice architecture.** Bogard: "my architecture is built around distinct requests, encapsulating and grouping all concerns from front-end to back". A slice is one use case; a module is a whole bounded context and holds many use cases. The two can nest later; this plan doesn't adopt slices.
11. **Rejected suggestions:** prefixing table names by module (python-ddd, arctikant) renames tables on live databases, a behaviour change this plan doesn't make; a schema per module (kgrzybek, evolutionary-architecture) likewise; replacing the cross-module foreign keys with event-driven copies (kgrzybek's Meetings keeps its own Members) changes behaviour too.

**Our own codebase** (studied at v0.19.0, `b2b061d`; full notes in `ai_research/16-modular-monolith/notes/our-codebase.md`, and every cross-module import in `notes/our-codebase-module-map-at-v0.19.0.txt`, from `ai_research/tools/module_map.py`):
- 284 source files and 205 test files; 50 wiki pages name `src/app/...` paths (885 times).
- **Four composition roots, on purpose** (plan 8): the web app (`CoreProvider` and the outbound providers), the public API (`PublicApiProvider`), the CLI (`CliProvider`) and the worker (`WorkerProvider`) each build their own container, because some ports bind to different adapters per entrypoint. So a module contributes wiring **per entrypoint**.
- **Identity never imports Organizations.** Organizations imports Identity 25 times: `CurrentUserService`, `UserFinder`, `Username`, the `User` entity, `AuthenticationError` (every organizations route), the public API's key header and error, `get_strenum_values`, and `users_table`, which `sqla_organization_reader.py` and `sqla_organization_repository.py` JOIN directly.
- **Notifications** is only imported by the composition roots; its handlers import only other modules' events.
- **The email transport is used by the HTTP error alerting** (`inbound/http/errors/exception_middleware.py` sends alert emails through `EmailSender`), so it can't live in a removable Notifications module.
- **`SqlaFlusher` maps unique-constraint names to Identity's errors** (`EmailAlreadyExistsError` and others), so each module must contribute its own mappings.
- **Foreign keys into Identity:** `organizations` and `organization_memberships` reference `users.id` (memberships with `ON DELETE CASCADE`). They follow the module direction and stay.
- **Traps:** the outbox and Celery messages carry Python import paths; the wiki's dependency-graph generator assumes four top-level layers; `alembic/env.py` imports the settings loader. Each has its own step below.

## Design

### Modules

- **Shared kernel** (`app/shared/`), core only: base `Entity` and value object, `DomainEvent`, `BaseError`/`BusinessTypeError`, the generic authorization base (`Permission`, `authorize`, composite permissions, `AuthorizationError`), `Email`, `Description`, `UtcDatetime`, the id factory, `sentinels`, and the query-support types (pagination, sorting). Rule: nothing with business meaning; it imports no module and no platform code.
- **Platform** (`app/platform/`): generic technical capabilities, each a port plus adapters:
  - events: the `EventDispatcher` and `EventHandler` ports, `HybridEventDispatcher`, the outbox (`OutboxRepository`, `SqlaOutboxRepository`, the `event_outbox` mapping), event serialization;
  - persistence: the mapper registry and `MetaData`, `entity_load_events`, constraint names, the nullable-composite helpers, `Flusher`/`SqlaFlusher` (fed by each module's constraint-error mappings), `TransactionManager`/`SqlaTransactionManager`, `UtcTimer`/`SystemUtcTimer`, the Alembic environment and its single history;
  - email transport: the `EmailSender` port and its console and SMTP adapters (moved out of the earlier draft's Notifications, because error alerting needs it);
  - HTTP plumbing with no domain imports: the error-aware router, rules, callbacks and OpenAPI error responses, the health checks, `missing.py`, and `StorageError`/`ReaderError`;
  - later: file storage, search, rate limiting.
  Rule: no business meaning; imports only the shared kernel.
- **Identity** (`app/modules/identity/`): users, account (sign up, log in, log out, change password, own profile), auth sessions (today's `outbound/auth_ctx/`), the cookie middleware, API keys and the public API's key authentication, admin user management, the users CLI, and (after plan 14) the staff grants.
- **Organizations** (`app/modules/organizations/`): organizations, memberships, invitations, organization authorization (`CurrentOrganizationService`, `MembershipChecker`), and (after plan 14) its RLS rules. Depends on Identity.
- **Notifications** (`app/modules/notifications/`): what is sent and when: today the welcome-email and invitation-email handlers (later templates, preferences, SMS). Depends on Identity and Organizations only through their published events; nothing depends on it.
- **`main/`** stays the composition root: the four entrypoints, settings, the module registry, and the entrypoint-specific HTTP pieces that need several modules (the global exception middleware with its alerting, the root routers).

Module dependency order (enforced): Notifications → Organizations → Identity. Every module may use `platform` and `shared`.

### Layout

```
src/app/
  shared/                       ← shared kernel (core code only)
  platform/
    core/                       ← ports: EventDispatcher, EventHandler, OutboxRepository, Flusher,
                                  TransactionManager, UtcTimer, EmailSender
    inbound/http/               ← error-aware router, rules, callbacks, OpenAPI responses, health, missing.py
    outbound/                   ← dispatcher, outbox, persistence (registry, Alembic), email adapters
  modules/
    identity/
      core/
        common/                 ← entities, value objects, events, authorization, ports, services
        commands/
        queries/
      inbound/
        http/                   ← private routes, public-API routes, cookie middleware
        cli/                    ← its CLI commands (today's main/cli/users/)
      outbound/                 ← adapters, auth sessions (today's auth_ctx), table mappings
      api.py                    ← its public API for other modules
      module.py                 ← its registration
    organizations/              ← the same shape
    notifications/              ← the same shape (core and module.py only, today)
  main/
    modules.py                  ← the registry: the one list of registered modules
    ...                         ← entrypoints, settings, DI composition, exception middleware, root routers
```

Where today's CLI lives (`main/cli/`, by the original author's decision, see `docs/plans/6-inbound-cli.md`): the CLI's own plumbing (its container, its identity provider) stays in `main/cli/`; only the user commands move into Identity, where they are registered like routers. Decision 6 covers this.

### A module's public API (`api.py`)

- **Starts as exactly what other modules use today, and nothing more** (finding 4). For Identity that is the 25 imports Organizations already makes (listed above), plus the events Notifications listens to. For Organizations, its published events.
- **Events are always public**; a module's domain events are its integration contract (ddd-by-examples, kgrzybek's IntegrationEvents projects). Kept as today's classes; no separate integration-event types (Decision 4).
- **New cross-module calls** (from search, file storage or a fork's modules) use the facade-plus-consumer-port pattern (finding 7).
- **Known couplings kept, listed and owned:** Organizations' SQL readers JOIN `users_table` (exposed through Identity's `api.py`), and the foreign keys into `users.id`. They are documented in Identity's `api.py` and the wiki, so they stay deliberate.

### The registry

Each module's `module.py` declares one module object; `main/modules.py` lists them. Everything below is built from that one list (finding 2). A module declares:
- its name, and the modules it depends on (the registry refuses to start, naming the missing module, if a dependency isn't registered: evolutionary-architecture's and kgrzybek's gap);
- **per entrypoint**, its dishka providers: web app, public API, CLI, worker (any may be empty);
- its private routers and public-API routers;
- its table-mapping functions (used by the app start-up and by `alembic/env.py`);
- its event subscriptions (event type → handler classes), replacing the hand-written registries in `CoreProvider` and `CliProvider`;
- its CLI command groups;
- its unique-constraint → domain-error mappings for `SqlaFlusher`;
- after plan 14: its RLS table rules (today's central `TABLE_RULES`), so the migration generator and the catalog guard read them from the registry;
- its seed-data function, if any.

Registration is a code list (Decision 2): plain, type-checked, reviewed in diffs. Each piece of the registry is new code, built test-first (Step 7).

### Enforcement (`lint-imports` in `make check`)

import-linter 2.15 (pinned) has every contract type needed: `layers` with wildcard containers and `exhaustive`, `forbidden`, `independence` and `protected` (added in 2.5). A sketch, settled for real in Step 6:

```toml
# Top level: main → modules → platform → shared.
[[tool.importlinter.contracts]]
id = "top-level"
type = "layers"
containers = ["app"]
layers = ["(main)", "modules", "platform", "shared"]
exhaustive = true

# Module order: Notifications → Organizations → Identity, never back.
[[tool.importlinter.contracts]]
id = "module-order"
type = "layers"
containers = ["app.modules"]
layers = ["notifications", "organizations", "identity"]
exhaustive = true

# Inside every module: inbound and outbound depend on core, never the reverse.
[[tool.importlinter.contracts]]
id = "module-layers"
type = "layers"
containers = ["app.modules.*"]
layers = ["(module)", "(api)", "inbound", "outbound", "core"]

# Other modules reach a module's internals only through its api.py (one contract per module).
[[tool.importlinter.contracts]]
id = "identity-internals"
type = "protected"
protected_modules = ["app.modules.identity.core", "app.modules.identity.inbound", "app.modules.identity.outbound"]
allowed_importers = ["app.modules.identity", "app.main"]
```

Plus today's CQRS contracts, written per module, and the `auth-ctx` contract at its new path. Known limits: `protected` checks direct imports only; the linter can't see dynamic imports, DI lookups, shared tables or event names travelling as strings. So the registry tests and the feature-delete test (Step 8) cover what imports can't.

### Tests and commands

- **Tests mirror the modules:** `tests/unit/modules/<name>/...` and `tests/integration/with_infra/modules/<name>/...`, plus `tests/unit/{shared,platform,main}/...` for the rest. Whole-app suites (`tests/sanity`, `tests/smoke`, `tests/integration/migrations`) stay where they are. Test helpers used by more than one module move to a shared test-support package.
- **`make check` and `make test-docker` are unchanged in what they run:** their path variables (`PYTEST_PATHS_LIGHT`, `PYTEST_PATHS_APP_INFRA`) already cover all of `tests/unit` and `tests/integration/with_infra`, so they still run every test.
- **New per-module commands** (path filters; the Python references all select by path, none uses markers):
  - `make test-module module=organizations`: that module's unit and no-infra tests, locally;
  - `make test-docker-module module=organizations`: that module's infrastructure tests in the Docker test stack (the same stack as `make test-docker-file`).
  Each prints an error naming the valid modules if `module` is missing or unknown. Whether these Makefile targets get human checks only (as `OPEN_DASHBOARDS` did) is Decision 7.

### Settings

The 13 settings classes stay in `main/config/settings.py`, with their loader tests, for now (Decision 5). A module's providers keep receiving them through dishka context as today.

### Things to think about: what stays single for now

Practical compromises, accepted for now and revisited later (human maintainer, 2026-10-17):
- **Alembic migrations:** one history for every module (finding 8). The trade-off: a module can be removed from the code, but its tables and migrations stay. Labelled per-module bases can be added later without rewriting existing history.
- **The SQLAlchemy mapper registry and `MetaData`:** one, in `platform/`. Each module contributes only its own mapping functions; `env.py` builds its target metadata from the registry.
- **The database:** one database and one schema, table names unchanged.
- **The event outbox:** one shared `event_outbox` table in `platform/`, not one per module as in kgrzybek.

### Existing files this touches (flagged, per `agents.md` 3.1)

Nearly every file moves. Under the 3.1 exception: original-author files are relocated, never rewritten. These change in content, because they are the hand-written composition the registry replaces: `main/ioc/core.py`, `main/ioc/outbound.py`, `main/ioc/provider_registry.py`, `main/ioc/public_api.py`, `main/cli/provider.py`, `main/cli/root_group.py`, `main/worker/provider.py`, `main/run.py`, `main/run_public_api.py`, `inbound/http/root_router.py`, `inbound/http/api_v1_router.py`, `inbound/http/public_api/router.py`, `outbound/persistence_sqla/mappings/all.py`, `outbound/persistence_sqla/alembic/env.py`, `outbound/adapters/sqla_flusher.py`, `outbound/adapters/event_serialization.py` (Decision 3), `scripts/seed_db.py`, `scripts/wiki/dependency_graph.py`, `pyproject.toml`, `alembic.ini`, `Makefile`.

## Decisions for the human maintainer

1. **Migrations: one Alembic history** (decided 2026-10-17, see "Things to think about"). Recorded here for completeness.
2. **How a module is registered and deregistered.** Recommended **(a)**: a code list in `main/modules.py` (python-ddd, lato). **(b)** a setting such as `ENABLED_MODULES` (evolutionary-architecture's per-module flags) is more flexible but is a new setting (with its loader test, `agents.md` 2.3) and lets a misconfiguration switch off a required module, so it needs the dependency check at start-up either way. (a) can grow into (b) later.
3. **Outbox rows and Celery messages in flight across the deploy.** Both carry the event's and the handler's import path (`HybridEventDispatcher` stores `dotted_path(type(event))` and `dotted_path(type(handler))`; the worker resolves them with `import_from_dotted_path`). Moving those classes orphans anything created before the deploy. **(a)** A deploy procedure only: stop the web app, let the worker drain the outbox and the queue, then deploy. No code, but every fork must follow it. **(b) Recommended:** a small, test-first mapping from the old paths to the new ones inside `import_from_dotted_path`, kept for one release and then removed (a dated follow-up), so no fork can lose an email by deploying normally.
4. **Integration events.** Recommended: keep today's event classes as the public contract, exposed through each module's `api.py`. kgrzybek's separate integration-event types (domain events kept private, small translated events published) add a type and a translation per event; worth it only when an event's internals start leaking. Revisit with the first fork module.
5. **Settings:** recommended to stay in `main/config/` for now (no loader-test churn); a module could own its settings classes later.
6. **The CLI's place.** Today's CLI lives in `main/cli/` by the original author's decision. Recommended: its plumbing stays there and only the user commands move into Identity's `inbound/cli/`, registered through the registry. The alternative is leaving the whole CLI in `main/` and registering nothing.
7. **Testing the new Makefile targets.** They are shell, with no automated tests, like `OPEN_DASHBOARDS`. Under `agents.md` 2.1, "not worth an automated test" is the human maintainer's call: human checks only, or a small pytest that runs them through `make -n` and checks the paths they select.
8. **Roadmap item "group `core/commands/` and `core/queries/` by area".** This plan supersedes it: grouping by module does that and more. Recommended: mark it superseded when this plan ships.

## Proposed changes

Every move step follows the same discipline: before it, record `make check` and `make test-docker` counts; move one area **with its tests**; update imports, the import-linter contracts and the paths in `pyproject.toml` and `alembic.ini` that name it; then `make check` and `make test-docker` must show the same counts, all green, and the characterisation tests from Step 0 must still pass. A move step adds no behaviour. Every step that adds code is RED first, then GREEN (`agents.md` 2.1).

0. **Preconditions and characterisation tests.**
   - Plan 14 finished and committed; `git status` clean; `make check` and `make test-docker` green; counts recorded here.
   - Characterisation tests, written before anything moves, that pin today's behaviour so every later step proves it unchanged. They pass on day one (confirmation tests, said so explicitly):
     - both OpenAPI documents (the web app's and the public API's) equal a committed snapshot;
     - each of the four DI containers builds, and resolves every command, query and handler it resolves today;
     - the event subscriptions are exactly today's (UserRegistered → SendWelcomeEmail, OrganizationInvitationCreated → SendOrganizationInvitationEmail), in the web app and the CLI;
     - the mapped tables are exactly today's six;
     - the CLI command list is exactly today's.
1. **Shared kernel.** Relocate the building blocks to `app/shared/`. Add the `top-level` contract with `(main)`, `(modules)` and `(platform)` as optional layers until they exist. RED for the contract itself: a deliberate import from `shared` into another layer, seen failing, then removed.
2. **Platform.** Relocate the events machinery, the outbox, the persistence infrastructure, the email transport and the domain-free HTTP plumbing to `app/platform/`. `alembic.ini`'s `script_location` and the layers contract's two `alembic.env` ignores move with it.
3. **Identity.** Relocate users, account, auth sessions, API keys, admin user management, the cookie middleware and the user CLI commands, with their tests, to `app/modules/identity/`. Create its `api.py` with exactly the names other code imports from it today.
4. **Organizations.** Relocate organizations, memberships and invitations, with their tests, to `app/modules/organizations/`; switch its imports of Identity to `identity.api`.
5. **Notifications.** Relocate the two email handlers, with their tests, to `app/modules/notifications/`.
6. **Contracts between modules.** Add `module-order`, `module-layers`, one `protected` contract per module, the per-module CQRS contracts, and `exhaustive` where the sketch has it. Each new contract gets its deliberate RED.
7. **The registry, test-first.** First RED: building the web app from a given list of modules exposes only those modules' routes in the OpenAPI document. Then one RED/GREEN cycle each for:
   - the module object and the dependency check (an unregistered dependency refuses to start, naming it);
   - routers (private and public API);
   - providers, per entrypoint;
   - table mappings, including `alembic/env.py` building its target metadata from the registry;
   - event subscriptions, replacing the hand-written handler registries;
   - CLI command groups;
   - constraint-error mappings for `SqlaFlusher`;
   - RLS table rules (plan 14's `TABLE_RULES`, its migration hook and its catalog guard);
   - seed data (`scripts/seed_db.py`).
   After each, the characterisation tests still pass unchanged.
8. **The feature-delete test.** An integration test builds the app without Notifications: it starts, sign-up succeeds, no email is sent, and nothing else changes. A second test proves a module whose dependency is unregistered refuses to start.
9. **Import paths in flight** (Decision 3). If (b): RED, an outbox row written with an old path is delivered; GREEN, the mapping; and a dated follow-up to remove it.
10. **Per-module test commands.** `make test-module` and `make test-docker-module`, tested per Decision 7.
11. **The wiki generator, test-first.** `scripts/wiki/dependency_graph.py` learns `app.modules.<name>.<layer>` (RED: its tests, extended with module paths, fail on today's `parts[1]` logic) and adds a module-level graph. Then the wiki: the pages naming moved paths (paths updated, prose kept per `agents.md` 3.3), a new page on the module structure and how to add a module, `CHANGELOG.md` and the version, and the roadmap and README.

## File summary

| Today | After |
|---|---|
| `core/common/{entities/base,value_objects/{base,description,email,utc_datetime},events/domain_event,exceptions,sentinels,factories/id_factory}`, `core/common/authorization/{base,authorize,composite,exceptions}`, `core/queries/query_support/` | `shared/` |
| `core/commands/ports/{flusher,outbox_repository,transaction_manager,utc_timer}`, `core/common/ports/{event_dispatcher,event_handler,email_sender}` | `platform/core/` |
| `outbound/adapters/{hybrid_event_dispatcher,event_serialization,outbox_message,sqla_outbox_repository,sqla_flusher,sqla_transaction_manager,system_utc_timer,console_email_sender,smtp_email_sender}`, `outbound/persistence_sqla/{registry,entity_load_events,constraint_names,mappings/composite,mappings/outbox_message,alembic}`, `outbound/exceptions` | `platform/outbound/` |
| `inbound/http/errors/{router,rules,callbacks,openapi_responses,internal_server_error}`, `inbound/http/health/`, `inbound/missing.py` | `platform/inbound/http/` |
| everything about users, account, sessions, API keys (`core/...user*`, `core/...api_key*`, `outbound/auth_ctx/`, `inbound/http/{account,users}/`, `inbound/http/public_api/{account,api_keys}/`, `inbound/http/auth_cookie_middleware.py`, `main/cli/users/`, the users, auth_sessions and api_keys mappings) | `modules/identity/` |
| everything about organizations, memberships and invitations (`core/...organization*`, `inbound/http/organizations/`, `inbound/http/public_api/organizations/`, their adapters and mappings) | `modules/organizations/` |
| `core/common/events/handlers/` | `modules/notifications/core/` |
| `inbound/http/errors/{exception_middleware,alerting}`, `inbound/http/{root_router,api_v1_router,debug}/`, `inbound/http/public_api/router.py` | `main/` (entrypoint-specific HTTP composition) |
| (new) | `modules/*/module.py`, `modules/*/api.py`, `main/modules.py`, the registry and its tests, the characterisation tests, the per-module Makefile targets |

The exact per-file list comes from `ai_research/tools/module_map.py` and is reviewed at each move step; a file whose module is unclear is a question for the human maintainer, not a guess.

## Follow-ups and non-goals

- **Remove the old-path mapping** after one release, if Decision 3 is (b).
- **Per-module migration histories,** if a module ever has to be removable together with its tables.
- **Tighten the public APIs** later (for example, Organizations' JOINs on `users_table` through a facade), each as its own change with its own tests, never during this plan.
- **Search and file storage** (`docs/plans/11-search.md`, `docs/plans/12-file-storage.md`): their designs predate this plan; their paths are revised to the module layout before each starts.
- **A matching frontend:** the roadmap's "Frontend template" note describes the same module-per-bounded-context shape.
- **Not goals:** separate services, separate databases or schemas, runtime plugin loading, vertical slice architecture, renaming tables, or fixing any known issue along the way.

## Verification plan

- Every move step: the same `make check` and `make test-docker` counts before and after, all green, plus the Step 0 characterisation tests unchanged.
- Every new behaviour: RED with `uv run pytest <unit file> -v` or `make test-docker-file path=...`, GREEN with `make check`; `make test-docker` before every commit.
- Architecture: `lint-imports` with the contracts above, each contract proven by a deliberate RED.
- Human checks, written into this plan as each step lands, in the `docs/plans/agents.md` 1.3 format (exact commands, seeded accounts, no placeholders). They will cover: both OpenAPI documents unchanged; a `curl` through each module's routes with a read-back; the worker delivering a welcome email; the CLI listing users; each per-module test command; and the app with Notifications deregistered.
