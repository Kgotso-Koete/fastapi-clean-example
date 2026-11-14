# 16. Modular monolith: a first step (Option B: the original app in `src/app/base/`)

> **Status: done (v0.20.0, 2026-11-14): Steps 0 to 8 done (Step 2b dropped on 2026-10-30), and every human check passed on 2026-11-14** (research done 2026-10-17; redesigned with the human maintainer on 2026-10-22 and 2026-10-23). **Sequencing:** this restructuring comes before search and file storage (`docs/plans/11-search.md`, `docs/plans/12-file-storage.md`), which are then built straight into modules (decided by the human maintainer, 2026-10-17; recorded in `docs/plans/0-production-readiness-roadmap.md`). It was to follow plan 14 (`docs/plans/14-row-level-security.md`), which was parked on 2026-10-21 and no longer comes first. **Scope changed on 2026-10-22:** instead of turning every bounded context into a module (Identity, Organizations, Notifications, plus a shared kernel and a platform module), only Organizations and Notifications become modules (Decision 9). **Layout changed on 2026-10-23 to Option B** (Decision 17): the original author's app moves, unchanged below one prefix, into `src/app/base/`; the modules go in `src/app/modules/`; our shared technical code goes in `src/app/shared/`, so the top level holds only units and every unit has the same layers inside. Open questions are listed under Decisions; the work starts from v0.19.1 on the branch `feature/modular-monolith`. It lands in one commit, at the end (Decision 16, as amended on 2026-11-11).
>
> **Ground rules for this plan** (human maintainer, 2026-10-17):
> - **The one exception to the original-author rule.** This restructuring is the only time this codebase makes major changes to the original author's code. The exact terms are in `docs/plans/agents.md` 3.1: files are relocated, never rewritten; the hand-written composition (DI providers, routers, table mappings) may change so the app is built from a registry of modules; nothing else. Under Option B the original author's files are relocated under one prefix, `src/app/base/`, with nothing below the prefix changing; only the hand-written composition, and the paths that name moved files, change.
> - **A clean bill of health first.** It starts from a released commit with nothing uncommitted and nothing half-done. Every known behaviour is the same afterwards, including the known open issues listed in the roadmap (they are fixed separately, never during this plan).
> - **Every diff contains only the move.** While files, functions and paths are relocated, an edit changes only the text the move requires: a module path, a file path, an import. Nothing is wrapped, joined, reflowed or tidied, even when inserting a path pushes a line past the 120-character limit. Any formatting the move makes necessary is done afterwards, in its own separately approved step with its own diff, so every diff of a move can be checked at a glance. The human maintainer's words (2026-10-29): "We want to makes sure changes are only related to moving file, functions, etc around. This rule is only for this modular monolith plan implementation. Why increase the cognitive overhead of reviews by making me review unrelated changes for such sensitive restructuring?"
> - **TDD for every piece of new code** the restructuring needs (the registry, the module contracts, the import-boundary tests, the wiki generator changes). Only pure moves are exempt, and they are proven by unchanged test counts and characterisation tests instead (Step 0).
> - **`make check` and `make test-docker` still run every unit and every integration test.** New commands run one module's tests on their own.

## Goal

Take the first step from today's layer-first structure towards a **modular monolith**: one process, one database, one Alembic history, with each bounded context that is ours (not the original author's) in its own module folder, the original author's Clean Architecture layers repeated inside it, and module boundaries enforced by import-linter and tested.

- The original author's app moves into `src/app/base/` with its shape untouched (`src/app/base/core/`, `src/app/base/inbound/`, `src/app/base/outbound/`, `src/app/base/main/`). It is the base the modules build on, and it stays the design north star: in the human maintainer's words, "the further we drift from this the higher the risk and technical debt."
- Organizations and Notifications move into `src/app/modules/`; email's implementations move into `src/app/shared/`, the home for the shared technical code search and file storage will add.
- The composition root (`src/app/base/main/`) builds the app from **one registry** instead of naming every module's router, provider and mapping by hand.
- A module that nothing else depends on (Notifications today, a fork's own business module later) can be deregistered by removing it from the registry, and the rest of the app still starts and passes its tests.
- If this works, Identity (users, account, sessions, API keys, the CLI's user commands) can follow later, as its own plan.

## User stories

Not user-facing: no route, response or behaviour changes. These are for developers of this template and its forks.

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. One place per domain | developer on a fork | all of one bounded context's code in one folder | I can understand and change a domain without hunting across layer folders | Each module holds its own `core/`, `inbound/`, `outbound/` and `main/` (only the ones it needs)<br>Its tests mirror it<br>A new business domain is added as a new module |
| 2. Enforced boundaries | maintainer | units to depend on each other only in allowed directions | a shortcut import can't quietly couple two domains | `make check` fails if `base` imports a module or `shared`, a module imports another module's internals or `shared`, or modules depend on each other both ways<br>The same layer rules hold inside every unit<br>Every rule has a test that proves it catches a violation |
| 3. One registry | developer on a fork | to register a module in exactly one place | nothing drifts out of step | The web app, the public API, the CLI and the worker all build their module wiring from the same registry |
| 4. Removable modules | developer on a fork | to remove a module nothing depends on, by removing one registry entry | a template feature I don't need can be dropped cleanly | With Notifications removed, the app starts, sign-up still succeeds and no email is sent<br>A module whose dependency is missing from the registry refuses to start, naming the missing module |
| 5. All tests at once | developer or CI | one command for the light tests and one for the infrastructure tests, covering every unit | nothing can be left untested when units are added | `make check` runs the linters over the whole codebase and the light tests of `base`, every module and `shared`<br>`make test-docker` runs every unit's tests, infrastructure tests included<br>A newly added module's tests are picked up without editing either command |
| 6. One unit's tests | developer | to run the tests of only the unit I'm changing (`base`, one module, or `shared`) | I get fast feedback without waiting for the whole suite | A per-unit command (names in O6) runs exactly that unit's light tests locally, and another its infrastructure tests in the Docker test stack<br>The whole-app suites (sanity, smoke, migrations) run with `base`<br>Each unit's test count, added up across all units, equals the full suite's count, so no test is skipped or run twice |
| 7. Nothing changes for users | API client | every route to behave exactly as before | the restructuring is invisible | Both OpenAPI documents are identical before and after<br>The same test counts pass before and after every move step |
| 8. Upstream stays intact | maintainer | the original author's code to keep its shape | I can keep porting the original author's updates, path for path below one prefix, as `docs/plans/15-upstream-autumn-2026.md` did | Every original-author file keeps its path below `src/app/base/` (prefix added, nothing else)<br>Only hand-written composition files, and the paths that name moved files, change |

## What the research found

Studied 2026-10-17; three more references added at the human maintainer's request on 2026-10-23 (the last three rows below, notes in `notes/shared-code-references-2026-10-23.md`). **Local copies, for re-reading:** `ai_research/16-modular-monolith/` at the repository root (git-ignored, so only on the machine that downloaded it): `repos/` (15 cloned repositories), `web/` and `text/` (17 articles and docs pages; the text made with `ai_research/tools/to_text.py`), and `notes/` (one findings note per group of sources, with file paths). If the folder is missing, rebuild it from the URLs below. Trust signals checked on GitHub the same day.

**The references** (per `docs/plans/agents.md` 6.2):

| Repository | Stars / forks / contributors | Created | What it contributed |
|---|---|---|---|
| https://github.com/kgrzybek/modular-monolith-with-ddd | 14.1k / 2.2k / 33 | 2019 | The canonical reference, and the best one found for Clean Architecture inside every module; the module shape, events between modules, and its failures (below) |
| https://github.com/spring-projects/spring-modulith | 1.2k / 228 / 95 | 2022 | Precise boundary rules, module isolation tests, and the outbox-style event publication registry |
| https://github.com/Shopify/packwerk (+ three Shopify engineering articles) | 1.9k / 123 / 83 | 2020 | What went wrong enforcing boundaries at scale |
| https://github.com/ddd-by-examples/library | 5.9k / 833 / 22 | 2019 | Choosing contexts, one-way integration by events, direction-only architecture tests |
| https://github.com/ThreeDotsLabs/wild-workouts-go-ddd-example | 6.5k / 589 / 13 | 2020 | Consumer-owned ports, one composition function per context |
| https://github.com/Sairyss/domain-driven-hexagon | 15.0k / 1.6k / 20 | 2020 | Module rules in prose, and their breakage in its own code |
| https://github.com/evolutionary-architecture/evolutionary-architecture-by-example | 3.6k / 541 / 9 | 2023 | A module registry (`Chapter-2-modules-separation/Src/Fitnet/Modules/ModulesRegistry.cs`) with per-module enabled flags |
| https://github.com/pgorecki/python-ddd and https://github.com/pgorecki/lato | 1.0k / 127 / 3; 216 / 7 / 2 | 2018; 2023 | Python modular monolith: explicit module list, events in one transaction |
| https://github.com/cosmicpython/code | 2.7k / 1.1k / 6 | 2019 | The Python reference for the patterns this repo already uses |
| https://github.com/arctikant/fastapi-modular-monolith-starter-kit | 55 / 12 / 1 | 2024 | The "gateway" facade (`app/auth/gateway.py`), recommended by the human maintainer |
| https://github.com/Khaled-Farhat/modular-monolith-practice | 2 / 1 / 1 | 2026 | The cleanest cross-module call pattern found, recommended by the human maintainer (weak trust signal) |
| https://github.com/seddonym/import-linter | 1.2k / 89 | 2019 | The boundary checker this repo already uses (pinned at 2.15) |
| https://github.com/kgrzybek/modular-monolith-with-ddd/tree/master/src/BuildingBlocks/Application | (part of kgrzybek, above) | 2019 | The shared ports every module uses (`IEmailSender`, `IOutbox`, `IExecutionContextAccessor`, paging), with their one implementation in `src/BuildingBlocks/Infrastructure/` and each module registering it (`src/Modules/UserAccess/Infrastructure/Configuration/Email/EmailModule.cs`) |
| https://github.com/baranacikgoz/modular-monolith-ddd-vsa-webapi | 167 / 16 / 5 (one human author, plus bots and one AI-agent commit) | 2023 | Two module tiers, `IModule` and an always-loaded `ICoreModule` (`src/Common/Common.Infrastructure/Modules/IModule.cs`); shared storage ports and S3 adapters (`src/Common/Common.Application/Storage/`); email inside its Notifications module; architecture tests that derive the module list and prove each detector on a fixture first (weak trust signal: mostly written 2024 to 2026, rules kept in a `CLAUDE.md`) |
| https://github.com/foxminchan/Modulith | 30 / 14 / 1 | 2024 | Shared code split into a domain kernel, technical infrastructure and persistence (`src/Modulith.SharedKernel`, `src/Modulith.Infrastructure`, `src/Modulith.Persistence`); storage kept inside the one module that uses it; a `Contracts` project per module (weak trust signal: 10 commits in one week, empty test projects) |

Articles: Kamil Grzybek's modular monolith series (https://www.kamilgrzybek.com/blog/posts/modular-monolith-primer and its four sequels), Shopify's "Deconstructing the Monolith" (https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity), "Under Deconstruction" (https://shopify.engineering/shopify-monolith) and "A Packwerk Retrospective" (https://shopify.engineering/a-packwerk-retrospective), the Spring Modulith reference docs (https://docs.spring.io/spring-modulith/reference/fundamentals.html), Jimmy Bogard on vertical slices (https://www.jimmybogard.com/vertical-slice-architecture/), Martin Fowler's MonolithFirst (https://martinfowler.com/bliki/MonolithFirst.html), and the Alembic branches (https://alembic.sqlalchemy.org/en/latest/branches.html), dishka components (https://dishka.readthedocs.io/en/stable/advanced/components.html) and FastAPI bigger-applications docs (https://fastapi.tiangolo.com/tutorial/bigger-applications/).

**Findings that shaped the design:**

1. **No Python repo has a complete module contract, and none enforces its boundaries with a tool.** None of the five Python repos has one module object bringing its own providers, routers, mappings and handlers, none uses dishka, and none runs import-linter or an equivalent. Every one relied on convention and broke it, even in its own tests (Khaled-Farhat's test fakes import other modules' private `internal` code; python-ddd's bidding module imports `catalog.domain.events`; domain-driven-hexagon's wallet module imports user's event by its internal path, though its README forbids it). So this plan designs the contract itself, and enforcement is automatic from day one.
2. **Register each module in exactly one place, and derive everything from it.** kgrzybek's host lists every module by hand twice (`src/API/CompanyName.MyMeetings.API/Startup.cs`), its architecture tests keep their own module lists, and the newest module (Registrations) is missing from both: half-wired, and unchecked. evolutionary-architecture's `ModulesRegistry` and python-ddd's explicit module list are the better shape.
3. **Enforcement must be proven, not assumed.** One of kgrzybek's layer tests checks the wrong project, so its rule never runs (`src/Modules/Meetings/Tests/ArchTests/Module/LayersTests.cs`, the second test). Here every import rule gets a test that runs it against a small fake import graph containing one forbidden import and expects it to be caught. This replaces the earlier idea of adding a forbidden import to the application on purpose, which `docs/plans/agents.md` 2.1 forbids ("Never break application code to prove a test can fail").
4. **Dependencies first, privacy second, and keep the public API small.** Shopify removed Packwerk's privacy checks in 3.0: the `app/public` folders filled with "poorly-documented public code that was never meant to be public", and developers designed APIs instead of asking whether the dependency should exist at all. Their debt is "a long way from being paid off". So the first contracts enforce direction; each module's public API starts as exactly what other modules already use today, and is never grown speculatively.
5. **Prove isolation by running code.** Shopify found packages with zero violations that still failed to boot alone ("running code, more than any metric, will always be the best indicator of real progress"). Spring Modulith's `@ApplicationModuleTest` boots one module with the others mocked. Here: the feature-delete test boots the app without Notifications.
6. **Modules integrate one way, through events, with the listener depending on the publisher.** ddd-by-examples (catalogue → lending), Spring Modulith (listeners after commit, an event publication registry that is effectively an outbox), and kgrzybek (outbox and inbox per module). This repo's dispatcher and transactional outbox already do this. kgrzybek's bus throws when an event has no subscriber (`src/BuildingBlocks/Infrastructure/EventBus/InMemoryEventBus.cs`), which makes removing a module break its publishers; this repo's dispatcher already ignores events nobody handles (`tests/unit/outbound/adapters/test_hybrid_event_dispatcher.py::...test_ignores_events_with_no_registered_handlers`), which is what makes Notifications removable.
7. **Synchronous calls between modules use a facade owned by the provider and a port owned by the consumer.** arctikant's gateway (`app/auth/gateway.py`: an ABC returning DTOs, exported from the module's `__init__`) is the provider side; Khaled-Farhat adds the consumer side: the consumer declares its own port (`app/orders/internal/core/ports/catalog_gateway_port.py`) and an outbound adapter calls the provider's facade (`app/orders/internal/shell/outbound/catalog_gateway_adapter.py`). wild-workouts does the same (`internal/trainings/app/command/services.go`). Recorded as the direction for new cross-module calls; today's existing calls stay as they are (Decision 4).
8. **One database and one migration history is normal.** Every Python reference uses one database and one shared metadata; kgrzybek keeps one central migrations folder and one history table even with a schema per module. Per-module Alembic histories are possible (multiple bases, `version_locations`, branch labels, `depends_on`), but the 9 existing linear revisions can't move, every `alembic upgrade head` call would change to `heads`, the stairway test assumes one `down_revision`, autogenerate compares one whole `MetaData`, and the docs warn branching "can get pretty crazy!". So one history stays.
9. **Plain per-module dishka providers, not dishka components.** Components isolate resolution, not imports, so import-linter is still the real boundary; every cross-component use would need `FromComponent`, FastAPI's `FromDishka` only reads the default component, and splitting shared providers could give each component its own session inside one request, breaking the single transaction the outbox relies on.
10. **This plan is modules per bounded context, not vertical slice architecture.** Bogard: "my architecture is built around distinct requests, encapsulating and grouping all concerns from front-end to back". A slice is one use case; a module is a whole bounded context and holds many use cases.
11. **Rejected suggestions:** prefixing table names by module (python-ddd, arctikant) renames tables on live databases, a behaviour change this plan doesn't make; a schema per module (kgrzybek, evolutionary-architecture) likewise; replacing the cross-module foreign keys with event-driven copies (kgrzybek's Meetings keeps its own Members) changes behaviour too.
12. **Start small: the least risky step first** (2026-10-22). Fowler: "start with coarse-granularity to gain knowledge and split later"; Shopify's isolation work took months for a single package. Moving every bounded context at once (the earlier version of this plan) meant relocating nearly every original-author file into new places, splitting files that mix contexts, and reshaping the composition root. Moving only the two contexts that are ours keeps the original author's code intact (below one prefix, under Option B) and tests every mechanism the restructuring needs: Organizations exercises private and public routes, providers for two apps, table mappings and the joins and foreign keys into the base's `users` table; Notifications exercises event subscriptions across modules, the worker and CLI containers and running the app with a module removed.
13. **Where shared code lives** (2026-10-23, the last three references above). All three keep **ports at the base**: kgrzybek's `src/BuildingBlocks/Application/Emails/IEmailSender.cs`, baranacikgoz's `src/Common/Common.Application/Storage/IPublicObjectStore.cs` and `IPrivateObjectStore.cs`, foxminchan's `src/Modulith.SharedKernel`. Two keep the **shared technical implementations as shared code at the base** too (kgrzybek's `src/BuildingBlocks/Infrastructure/Emails/EmailSender.cs`, baranacikgoz's `src/Common/Common.Infrastructure/Storage/`), and baranacikgoz models its always-on technical parts (Outbox, BackgroundJobs) as **core modules** that load in every process ("Outbox and BackgroundJobs are not business modules, they are the platform", `docs/ARCHITECTURE.md` decision 2). Plan 16's `src/app/shared/` combines those two (a unit of its own, required by `base`), and its "What goes where" rule matches all three on ports. baranacikgoz puts email inside its Notifications module instead (`src/Modules/Notifications/Notifications.Application/Email/IEmailGateway.cs`), with other modules asking Notifications to send; recorded as the alternative not taken. foxminchan keeps storage inside the one module that uses it (`src/Modulith.Modules.Products/Infrastructures/Storage/Azure/`), the rule for code only one module needs. baranacikgoz's architecture tests also repeat findings 2 and 3: the module list is derived because a hard-coded one "silently missed any new module" (`src/Common/Common.Tests/Architecture/SolutionAssemblies.cs`), and each detector is proven on an in-memory fixture first (`AggregateChildEntityParameterTests.cs`).
14. **"Host" is a composition root, not a base** (2026-10-23). In the .NET references, "host" is the .NET Generic Host (`IHost`, `HostBuilder`, `WebApplication`): the object that owns the process, its lifetime, DI container, configuration and logging. Their Host projects hold startup and wiring only (baranacikgoz's `src/Host/Host/`, kgrzybek's `src/API/CompanyName.MyMeetings.API/`, evolutionary-architecture's `Chapter-2-modules-separation/Src/Fitnet/`); evolutionary-architecture's `Fitnet.AppHost` is a .NET Aspire project that orchestrates containers, closer to `docker-compose.yml`. Shared code has other names there (`BuildingBlocks`, `Common`, `SharedKernel`). Our `src/app/base/` holds the original author's whole app, Identity included, so it keeps the name `base`; only `src/app/base/main/` is a host in that sense.

**Our own codebase** (studied at v0.19.0, `b2b061d`, and re-read in full on 2026-10-22 at v0.19.1, `22d8e16`; notes in `ai_research/16-modular-monolith/notes/our-codebase.md`, and every cross-module import in `notes/our-codebase-module-map-at-v0.19.0.txt`, from `ai_research/tools/module_map.py`). Paths here are today's, before the move into `src/app/base/`:
- 284 source files and 205 test files; `pytest --collect-only` collects 852 tests (5 more deselected: the `slow` bcrypt tests in `tests/unit/outbound/test_bcrypt_password_hasher.py`).
- **Four composition roots, on purpose** (plan 8): the web app (`CoreProvider` and the outbound providers), the public API (`PublicApiProvider`), the CLI (`CliProvider`) and the worker (`WorkerProvider`) each build their own container, because some ports bind to different adapters per entrypoint. So a module contributes wiring **per entrypoint**.
- **The original app never imports Organizations except in composition** and in three files that must stop: `src/app/inbound/http/api_v1_router.py`, `src/app/inbound/http/public_api/router.py` and `src/app/outbound/persistence_sqla/mappings/all.py` (which `alembic/env.py` calls).
- **Organizations imports the original app** for `CurrentUserService`, `UserFinder`, `Username`, the `User` entity, `UserId`, `AuthenticationError`, the public API's key header and error, `get_strenum_values`, and `users_table`, which `sqla_organization_reader.py` and `sqla_organization_repository.py` JOIN directly. All of these stay allowed (rule 4 below).
- **Notifications** is only imported by the composition roots; its handlers import only events (`UserRegisteredEvent` from the original app, `OrganizationInvitationCreatedEvent` from Organizations).
- **Foreign keys into `users.id`:** `organizations` and `organization_memberships` reference it (memberships with `ON DELETE CASCADE`). They follow the module direction and stay.
- **Traps, each handled below:**
  - The outbox and Celery messages carry Python import paths, and under Option B every event and handler class gets a new one. Rows and messages written before a move aren't delivered after it; before 1.0.0 that is accepted and no mapping is built (Decision 3).
  - `src/app/main/config/settings.py` holds `OrganizationSettings` and `EmailSettings`, which modules and `shared` need, and they may not import `src/app/base/main/` (Decisions 14 and 15).
  - The CLI subscribes only `UserRegisteredEvent → SendWelcomeEmail`; the web app subscribes both events. Subscriptions are therefore per entrypoint.
  - dishka's default validation lets a later provider silently override an earlier one, so the container characterisation tests pin the concrete class each port resolves to, not just that it resolves.
  - Paths that name the original app's modules, all of which change in Step 2: `docker-entrypoint.sh` lines 12 and 20, `docker-compose.yml` line 91, the `Makefile` lines 237 and 244, `README.md` line 74, `tests/integration/with_infra/cli/test_list_users.py` lines 97 and 112, `scripts/seed_db.py`, `scripts/dishka/plot_dependencies_data.py`, `alembic.ini` line 8, and in `pyproject.toml` the import-linter contracts, the ruff per-file ignore, the slotscheck exclude and the coverage omit (`src/app/main/**`).
  - `src/app/main/config/loader.py` line 22 finds the repository root with `Path(__file__).resolve().parents[4]`; one level deeper it must be `parents[5]`. `tests/sanity/main/config/test_loader.py` and `tests/integration/migrations/test_stairway.py` depend on it.
  - Tests that pin paths and change with the moves: `tests/unit/outbound/adapters/test_event_serialization.py:18` (a literal dotted path), `tests/unit/main/wiki_tools/test_dependency_graph.py:63-64` (the alembic `ignore_imports`), `tests/unit/outbound/adapters/test_sqla_flusher.py:21` and `tests/unit/inbound/http/errors/test_callbacks.py:16` (logger names).
  - `scripts/wiki/dependency_graph.py` reads the layer from the second part of a module name (`app.<layer>`); after Step 2 every name starts `app.base.`, so it would see no layers and its real-graph test would pass without checking anything.
  - Test file names repeat across folders (22 basenames), so every new test folder needs an `__init__.py`.
  - `tests/sanity/inbound/http/conftest.py` builds both OpenAPI documents from the root routers alone; once routers come from the registry, it must build them the same way the real app does.
  - Shared integration fixtures live in `tests/integration/with_infra/conftest.py` (including the autouse `it_worker_runtime`) and `tests/integration/with_infra/api_keys/conftest.py` (`it_public_client`); a test only gets them if it sits below that folder, so module tests import them explicitly (see "Tests and commands").
- **Checked on 2026-10-22:** neither OpenAPI document has a module-path-qualified schema name (34 + 18 schemas), and operationIds come from function names and paths, so both documents can stay identical across pure moves.

## North star reference codebases for recaps

Chosen by the human maintainer on 2026-11-02, so that a recap after a session shuts down and resumes reads the same fixed set of files every time instead of the 15 cloned repositories (about 7,155 files, more than fits in one session). When a recap names `ai_research/16-modular-monolith/`, `repos/` is covered by exactly the 53 files below; `notes/` and `text/` are read in full as before; `web/` (the raw HTML behind `text/`) is skipped. Paths are relative to each repository's folder under `ai_research/16-modular-monolith/repos/`.

**The north star: kgrzybek/modular-monolith-with-ddd** (https://github.com/kgrzybek/modular-monolith-with-ddd, folder `kgrzybek__modular-monolith-with-ddd/`).
- **Why this one:**
  - plan 16 already ranks it first: "the canonical reference, and the best one found for Clean Architecture inside every module";
  - the strongest trust signals in the research: 14.1k stars, 2.2k forks, 33 contributors, started in 2019, before the wave of AI-written code (`docs/plans/agents.md` 6.2);
  - the same shape as plan 16: every module repeats the same layers (Domain, Application and Infrastructure there; `core`, `inbound`, `outbound` and `main` here); shared ports live at the base (`BuildingBlocks`, our `base` ports plus `shared`); modules talk through events with an outbox; every decision is an ADR; architecture tests enforce the boundaries;
  - Kamil Grzybek's five-article blog series in `text/kamil-*.txt` explains this exact repository.
- **Where plan 16 deliberately differs from it**, so we follow its shape, not its code:
  - one container per entrypoint, not one per module (finding 9; its ADR 0016 chose a container per module);
  - one schema, keeping the foreign keys into `users.id`; it uses a schema per module and copies data between modules (finding 11, rejected);
  - routes live inside their module; it keeps every controller in the host (its ADR 0005); we follow evolutionary-architecture here;
  - one registry; it lists its modules by hand in two places that have drifted (finding 2: `Startup.cs` initialises Registrations, which has no Autofac module and no architecture test);
  - its architecture tests have bugs: `LayersTests.DomainLayer_DoesNotHaveDependency_ToInfrastructureLayer` checks the Application assembly, the module lists are hand-kept, and `TestBase.AssertAreImmutable` stops at the first failing type (finding 3); we prove every rule on a fake graph instead;
  - it's C#, so the patterns carry over and the code doesn't. No Python repository qualifies (finding 1); plan 16 itself is the Python translation.
- **The 50 files to read:**
  - `README.md`;
  - the 17 design records in `docs/architecture-decision-log/`, every file in it (numbered `0001` to `0017`);
  - the host's `src/API/CompanyName.MyMeetings.API/Startup.cs`;
  - `src/BuildingBlocks/Application/` (13 files): `CompanyName.MyMeetings.BuildingBlocks.Application.csproj`, `Data/ISqlConnectionFactory.cs`, `Emails/EmailMessage.cs`, `Emails/IEmailSender.cs`, `Events/DomainNotificationBase.cs`, `Events/IDomainEventNotification.cs`, `IExecutionContextAccessor.cs`, `InvalidCommandException.cs`, `Outbox/IOutbox.cs`, `Outbox/OutboxMessage.cs`, `Queries/IPagedQuery.cs`, `Queries/PageData.cs`, `Queries/PagedQueryHelper.cs`;
  - one module end to end, Meetings:
    - its startup: `src/Modules/Meetings/Infrastructure/Configuration/MeetingsStartup.cs` and `MeetingsCompositionRoot.cs`;
    - its facade: `src/Modules/Meetings/Application/Contracts/IMeetingsModule.cs` and its implementation `src/Modules/Meetings/Infrastructure/MeetingsModule.cs`;
    - one use-case folder, `src/Modules/Meetings/Application/MeetingGroupProposals/AcceptMeetingGroupProposal/` (5 files: `AcceptMeetingGroupProposalCommand.cs`, `AcceptMeetingGroupProposalCommandHandler.cs`, `AcceptMeetingGroupProposalCommandValidator.cs`, `MeetingGroupProposalAcceptedNotification.cs`, `MeetingGroupProposalAcceptedNotificationHandler.cs`), chosen because it shows a command, a domain event turned into a notification, and an internal command scheduled from it;
    - its architecture tests, `src/Modules/Meetings/Tests/ArchTests/` (5 files: `CompanyName.MyMeetings.Modules.Meetings.ArchTests.csproj`, `Application/ApplicationTests.cs`, `Domain/DomainTests.cs`, `Module/LayersTests.cs`, `SeedWork/TestBase.cs`);
  - the system-level architecture tests, `src/Tests/ArchTests/` (4 files: `CompanyName.MyMeetings.ArchTests.csproj`, `Api/ApiTests.cs`, `Modules/ModuleTests.cs`, `SeedWork/TestBase.cs`).

**One narrow second source: evolutionary-architecture's Chapter 2, only for the registry** (https://github.com/evolutionary-architecture/evolutionary-architecture-by-example, folder `evolutionary-architecture__evolutionary-architecture-by-example/`).
- **Why:** its single `ModulesRegistry` (one `Add`/`Register` pair per module, every module listed once) is the registry shape plan 16 adopts (finding 2, Decision 2).
- **The 3 files to read:**
  - `Chapter-2-modules-separation/Src/Fitnet/Modules/ModulesRegistry.cs`;
  - `Chapter-2-modules-separation/Src/Fitnet/Modules/Module.cs`;
  - `Chapter-2-modules-separation/Src/Contracts/Fitnet.Contracts.Api/ContractsModule.cs`.

## Design

### Layout (Option B)

The top level of `src/app/` holds only **units**, and every unit uses the same layer names inside (Decision 17):

```
src/app/base/                       the original author's app, its shape untouched
    core/  inbound/  outbound/  main/
src/app/modules/organizations/      Organizations
    core/  inbound/  outbound/  main/
src/app/modules/notifications/      Notifications
    core/  main/
src/app/shared/                     our implementations of technical capabilities (from Step 5)
    outbound/  main/                (inbound/ arrives with file storage)
```

The mirroring rule (Decision 10) for every file that moves: **new path = the unit's folder + its path below `src/app/` today.** Folder and file names below the prefix don't change; folder names keep their meaning (`outbound/` means "adapters this code drives").
- The original app: `src/app/<path>` → `src/app/base/<path>` (for example `src/app/core/commands/create_user.py` → `src/app/base/core/commands/create_user.py`).
- A module's files: `src/app/<path>` → `src/app/modules/<name>/<path>` (for example `src/app/core/commands/invite_organization_member.py` → `src/app/modules/organizations/core/commands/invite_organization_member.py`).
- `shared`'s files: `src/app/<path>` → `src/app/shared/<path>`.
- Tests the same way: `tests/<path>` → `tests/base/<path>`, `tests/modules/<name>/<path>` or `tests/shared/<path>`.

### Dependencies

"X depends on Y" means code in X imports code from Y.

**Who depends on whom:**
1. `src/app/base/main/` (the composition root) depends on `src/app/modules/` (to register the modules), on `src/app/shared/` (to register `shared`), and on the rest of `src/app/base/` (to wire it up). Nothing depends on `src/app/base/main/`.
2. `src/app/modules/notifications/` depends on `src/app/modules/organizations/`, but only on its `core/api.py` (for `OrganizationInvitationCreatedEvent`), and on `src/app/base/` (for `UserRegisteredEvent` and the `EmailSender` port).
3. `src/app/modules/organizations/` depends on `src/app/base/` (`CurrentUserService`, `users_table`, the error router, and so on).
4. `src/app/shared/` depends on `src/app/base/core/` (for the ports it implements, such as `EmailSender`) and on `src/app/base/outbound/` (for shared adapter pieces, such as `StorageError`).
5. Inside `src/app/base/`: `src/app/base/inbound/` depends on `src/app/base/outbound/` and `src/app/base/core/`; `src/app/base/outbound/` depends on `src/app/base/core/`; `src/app/base/core/` depends on nothing in `src/app/`.

**Who never depends on whom:**
- `src/app/base/core/`, `src/app/base/inbound/` and `src/app/base/outbound/` never depend on `src/app/modules/`, `src/app/shared/` or `src/app/base/main/` (one recorded exception: `alembic/env.py`, see rule 1).
- `src/app/shared/` never depends on `src/app/modules/` or `src/app/base/main/`.
- `src/app/modules/organizations/` never depends on `src/app/modules/notifications/`.
- No module depends on `src/app/base/main/` or on `src/app/shared/`. Modules use `base`'s ports (for example `EmailSender`), never `shared`'s adapters.

**Needing something at run time is not importing it.** Notifications needs `shared` at run time but doesn't depend on it: it imports only the `EmailSender` port from `src/app/base/core/common/ports/email_sender.py`, and `src/app/base/main/` binds that port to `shared`'s console or SMTP adapter when the app starts. `base` needs `shared` the same way (its error alerting sends email). Import rules can't see run-time needs, so the registry records them ("Notifications needs `shared`", "`base` needs `shared`") and checks them at start-up, with a test.

### What moves

**Step 2: the whole original app** (pure move, Decision 17): `src/app/core/`, `src/app/inbound/`, `src/app/outbound/` and `src/app/main/` → `src/app/base/`, and `tests/{characterisation,integration,performance,sanity,smoke,unit}/` → `tests/base/`, by the rule above. Everything below the prefix stays as it is.

**Step 4: Organizations** (`src/app/modules/organizations/`), paths below `src/app/` today:
- `core/commands/`: `accept_organization_invitation.py`, `change_organization_member_role.py`, `create_organization.py`, `decline_organization_invitation.py`, `delete_organization.py`, `invite_organization_member.py`, `organization_exceptions.py`, `remove_organization_member.py`, `update_organization.py`, `ports/organization_repository.py`
- `core/common/`: `authorization/current_organization_service.py`, `authorization/organization_exceptions.py`, `authorization/organization_permissions.py`, `authorization/organization_ports.py`, `entities/organization.py`, `entities/organization_membership.py`, `events/organization_invitation_created.py`, `factories/organization_id_factory.py`, `factories/organization_membership_id_factory.py`, `organization_exceptions.py`, `value_objects/organization_name.py`
- `core/queries/`: `list_my_invitations.py`, `list_my_organizations.py`, `list_organization_members.py`, `ports/organization_reader.py`
- `inbound/http/organizations/` (all 13 files, `__init__.py` included) to `inbound/http/private_api/`, and `inbound/http/public_api/organizations/` (its 3 route files) to `inbound/http/public_api/`: the private and public routes sit side by side in the module (Decision 12), named for the app each serves (Decision 10's amendment of 2026-11-09)
- `outbound/adapters/`: `sqla_membership_checker.py`, `sqla_organization_reader.py`, `sqla_organization_repository.py`
- `outbound/persistence_sqla/mappings/`: `organization.py`, `organization_membership.py`
- `OrganizationSettings` (the class only) from `src/app/base/main/config/settings.py` to `src/app/modules/organizations/main/config/settings.py` (Decision 14)

**Step 3: Notifications** (`src/app/modules/notifications/`): `core/common/events/handlers/send_welcome_email.py` and `send_organization_invitation_email.py`.

**Step 5: email's implementations** (`src/app/shared/`, Decisions 15 and 17), to prove the "What goes where" rule on one small capability before search and file storage depend on it:
- `src/app/base/core/common/ports/email_sender.py` **stays**: the `EmailSender` port is a contract `base` owns (the error alerting and Notifications both use it)
- `outbound/adapters/console_email_sender.py` and `smtp_email_sender.py` → `src/app/shared/outbound/adapters/`
- `EmailSettings` (the class only) from `src/app/base/main/config/settings.py` to `src/app/shared/main/config/settings.py`
- the three `provide_email_sender()` bindings, out of `src/app/base/main/ioc/core.py`, `src/app/base/main/cli/provider.py` and `src/app/base/main/worker/provider.py`, into `src/app/shared/main/ioc/`

**Everything else stays in `src/app/base/`,** including Identity, API keys, the public API's entrypoint and Identity's public routes, the CLI, the worker, admin user management, the outbox, persistence and Alembic. Identity moves later, in its own plan, once this structure has proven itself.

### What changes in place (flagged per `agents.md` 3.1)

**Paths that name moved files** (Step 2; mechanical, no behaviour changes):
- `docker-entrypoint.sh` lines 12 and 20, `docker-compose.yml` line 91, the `Makefile` lines 237 and 244, `tests/base/integration/with_infra/cli/test_list_users.py` lines 97 and 112: `app.main.` → `app.base.main.`
- `README.md` line 74 (`uvicorn app.main.run:make_app`): one of the original author's documented commands. Under `agents.md` 3.4 the AI agent never "corrects" these; this is a path update the move makes necessary, so it is shown to the human maintainer for approval at Step 2.
- `scripts/seed_db.py` and `scripts/dishka/plot_dependencies_data.py`: imports.
- `src/app/base/main/config/loader.py` line 22: `parents[4]` → `parents[5]`, the one line of the original author's code that changes in content.
- `alembic.ini` line 8: `script_location = src/app/base/outbound/persistence_sqla/alembic`.
- `pyproject.toml`: the import-linter contracts, the ruff per-file ignore and the slotscheck exclude for the alembic folder, and the coverage omit (`src/app/base/main/**`).
- `Makefile`: `PYTEST_PATHS_LIGHT`, `PYTEST_PATHS_APP_INFRA`, `PYTEST_PATHS_MIGRATIONS` and `STAIRWAY_TEST`, for `tests/base/`, `tests/modules/*/` and `tests/shared/`.

**Hand-written composition** (Steps 3 to 5):
- `src/app/base/main/ioc/core.py`, `src/app/base/main/ioc/outbound.py`, `src/app/base/main/ioc/public_api.py`, `src/app/base/main/ioc/provider_registry.py`, `src/app/base/main/cli/provider.py`, `src/app/base/main/worker/provider.py`: the Organizations, Notifications and email bindings and the event-handler registries move out into the units' providers and the registry.
- `src/app/base/inbound/http/api_v1_router.py`, `src/app/base/inbound/http/public_api/router.py`, `src/app/base/inbound/http/root_router.py`: take module routers from the registry instead of importing them.
- `src/app/base/outbound/persistence_sqla/mappings/all.py` and `src/app/base/outbound/persistence_sqla/alembic/env.py`: map the module tables the registry lists.
- `src/app/base/main/run.py`, `src/app/base/main/run_public_api.py`, `src/app/base/main/cli/__main__.py`, `src/app/base/main/worker/celery_app.py`: pass the registry where routers, providers or mappings are built.
- `src/app/base/main/config/settings.py` (loses `OrganizationSettings` and `EmailSettings`) and `src/app/base/main/config/loader.py` (imports them from their units).
- `scripts/wiki/dependency_graph.py`: learns `app.base.<layer>` (Step 2), then modules and `shared` (Step 7).

### A unit's interface

A module has two interfaces, and neither is `inbound/` (which means "adapters that drive this module from outside the process": HTTP routes, CLI commands):

1. **How it plugs into the app**, read only by `src/app/base/main/`. This is composition, so it lives in the module's `main/`, mirroring `src/app/base/main/ioc/`:
   - `src/app/modules/<name>/main/module.py` (new): the module's registration (see "The registry");
   - `src/app/modules/<name>/main/ioc/` (new): its dishka providers, one per entrypoint it takes part in;
   - `src/app/modules/<name>/main/config/settings.py`, when it has settings.
2. **What other modules may use.** Events and ids are domain, so this lives in `core/`:
   - `src/app/modules/<name>/core/api.py` (new): re-exports exactly what other modules use today, and nothing more. For Organizations that is `OrganizationInvitationCreatedEvent` (Notifications listens to it). Notifications has none: nothing depends on it.

`shared` has the first interface only (`src/app/shared/main/module.py`, `main/ioc/`, `main/config/settings.py`), and no `core/api.py`: nobody imports it; `base/main/` binds its adapters to `base`'s ports. `base` needs no `api.py`: it isn't a module, and rule 4 below limits what each layer of a module may import from it.

### The registry

`src/app/base/main/modules.py` holds the one code list of registered units (Decision 2): the modules and `shared`. Each unit's `main/module.py` provides what the registry reads, limited to what Organizations, Notifications and `shared` need today (finding 4: never grown speculatively):
- its name, and the units it needs (Notifications needs Organizations, and from Step 5 `shared`, whose email binding it needs at run time though it imports nothing from it; import-linter can't see a need like that, so this declaration and its test are the only guard). The registry refuses to start, naming the missing unit, if a needed one isn't registered;
- whether `base` itself requires it (from Step 5, `shared`: `base`'s error alerting needs its `EmailSender` binding). This one isn't in the unit's `main/module.py`: `base` lists what it needs itself, as `BASE_NEEDS` in `src/app/base/main/modules.py` (Step 5e). The registry refuses to start without a unit `base` needs, naming it;
- **per entrypoint** (web app, public API, CLI, worker), its dishka providers (any may be empty);
- **per entrypoint**, its event subscriptions (event type → handler classes), replacing the hand-written handler registries in `CoreProvider` and `CliProvider`;
- its private routers (web app, under `/api/v1`) and its public-API routers (under `/public/v1`);
- its table-mapping functions (used by the app start-up, the CLI, the worker and `alembic/env.py`).

**The unit contract can't be a class in `src/app/base/main/`** that units import, because no unit may depend on `src/app/base/main/`. Decided (Decision 13, O7 closed 2026-11-03): the contract is a `typing.Protocol` defined in `src/app/base/main/`, and each unit's `main/module.py` simply provides the names it requires (for example `NAME`, `NEEDS`, `web_providers()`) without importing anything from `src/app/base/main/`. The registry lists the Python modules themselves, and mypy checks each one against the `Protocol` structurally, so the type check stays and no forbidden import exists.

Not in the registry, because nothing needs them yet: CLI command groups, `SqlaFlusher` constraint-error mappings (Organizations has no unique-constraint mapping of its own), RLS table rules, seed data. Each is added, test-first, by the plan that first needs it (Identity's move, plan 14).

Registration order matches today's include order (Organizations before Notifications), so both OpenAPI documents keep their path and tag order. `shared` comes first (Step 5d); it has no routes, so neither document changes.

### The public API

The public API is an entrypoint (a second FastAPI app with its own container, mounted at `/public`), not a bounded context, so it stays in the composition root, like the CLI and the worker (Decision 12):
- stays: `src/app/base/main/run_public_api.py`, `src/app/base/main/ioc/public_api.py`, `src/app/base/inbound/http/public_api/router.py`, and Identity's public routes `src/app/base/inbound/http/public_api/account/` and `src/app/base/inbound/http/public_api/api_keys/`;
- moves: Organizations' public routes, to `src/app/modules/organizations/inbound/http/public_api/` (Decision 10's amendment), registered through the registry. They keep importing `API_KEY_HEADER_NAME` and `ApiKeyAuthenticationError` from `src/app/base/outbound/adapters/api_key_identity_provider.py` (allowed by rule 4).
- API keys stay with Identity: `ApiKeyIdentityProvider` and `ApiKeyAccessRevoker` implement Identity's own ports, and the public app needs them to know who is calling. They move when Identity moves.

### What goes where (Decision 15, worked out against plans 11 and 12 on 2026-10-22)

**The constraint.** `base`'s lower layers may never depend on `shared` (see "Dependencies"). Every shared capability foreseen so far is also needed by Identity, which is in `base`: email (the error alerting in `src/app/base/inbound/http/errors/exception_middleware.py`), search (plan 11's user search needs `SearchQuery`), file storage (plan 12's user galleries and documents need `FileStorage`). So "everything shared goes into `shared`" breaks on the first use by Identity.

**The rule.** `base` depends on a port it owns; `shared` supplies the adapter; `src/app/base/main/` binds the two. Nothing in `base`'s lower layers imports `shared`.
- **`base`** owns the contracts: ports and domain types (`EmailSender`, `SearchQuery`, `FileStorage`, `UserSearch`).
- **`shared`** owns our implementations of technical capabilities and their settings (SMTP, local disk, S3, the Elasticsearch client).
- **Business modules** own their domain, including their own entity-specific adapters.
- **Listener modules** react to events: Notifications today; possibly a search-indexing module for plan 11's Elasticsearch backend.

**Applied to the next plans** (their own designs decide the details, starting from this):
- **Email (Step 5):** port `src/app/base/core/common/ports/email_sender.py` (stays); adapters `src/app/shared/outbound/adapters/{console,smtp}_email_sender.py`; `EmailSettings` in `src/app/shared/main/config/settings.py`; bindings in `src/app/shared/main/ioc/`.
- **Search (plan 11):** `src/app/base/core/common/value_objects/search_query.py` and `src/app/base/core/queries/ports/user_search.py`; `src/app/modules/organizations/core/queries/ports/organization_search.py`; `src/app/base/outbound/adapters/postgres_user_search.py` (it queries `users_table`, Identity's knowledge) and `src/app/modules/organizations/outbound/adapters/postgres_organization_search.py`; `SearchSettings` in `src/app/shared/main/config/settings.py`; the Elasticsearch client built in `src/app/shared/main/ioc/`. The two Elasticsearch adapters take the client as a constructor argument: they import the `elasticsearch` library, never `shared`.
- **File storage (plan 12):** `src/app/base/core/common/ports/file_storage.py`; `src/app/shared/outbound/adapters/local_disk_file_storage.py` and `s3_compatible_file_storage.py`; `StorageSettings` in `src/app/shared/main/config/settings.py`; the local backend's public-image route in `src/app/shared/inbound/http/`. Galleries and documents go with their owner: Identity's in `base`, Organizations' in `src/app/modules/organizations/`. Content checks and thumbnails: one more `base` port, its Pillow adapter in `shared`.

**What this means for `shared`:**
- **It is a unit of its own, not a module** (Decision 17): `modules/` holds bounded contexts only, and `shared` holds no business.
- **It is required, not removable:** `base` can't run without an `EmailSender` binding, so the registry marks it as required by `base` and refuses to start without it (see "The registry").
- **Settings move into it one class at a time** (`EmailSettings` now, `SearchSettings` and `StorageSettings` later), each still loaded by `src/app/base/main/config/loader.py`, with its loader test there.
- **The line is drawn by timing, on purpose.** By the rule, the outbox, the event dispatcher and the database session are also "our implementations of technical capabilities", but they stay in `base`: they are used everywhere, including by the worker, and moving them is not part of this plan. The rule applies to email and to new capabilities, and the module-structure wiki page says so.
- **An alternative for settings, recorded so Decision 14 stays deliberate:** the code already passes a setting to code that may not import the composition root through a `NewType` (`CeleryEnabled` in `src/app/outbound/adapters/hybrid_event_dispatcher.py`, filled from `CelerySettings` by `src/app/main/ioc/outbound.py`). The same could hand Organizations `INVITATION_TTL_DAYS` without moving `OrganizationSettings`.

### Import rules (`lint-imports` in `make check`, tested in `tests/base/unit/architecture/`)

Six kinds of rule (Decisions 11 and 17). Each is an import-linter contract in `pyproject.toml` (import-linter 2.15, pinned):

1. **The units, top to bottom, and `base`'s own layers.**
   ```toml
   # The dependency order between units. src/app/base/ appears twice: its main/ (the composition
   # root) is at the top, its other layers at the bottom, so each part is named on its own.
   [[tool.importlinter.contracts]]
   id = "unit-order"
   type = "layers"
   layers = ["app.base.main", "app.modules", "app.shared", "app.base.inbound", "app.base.outbound", "app.base.core"]
   ignore_imports = [
     "app.base.outbound.persistence_sqla.alembic.env -> app.base.main.config.loader",
     "app.base.outbound.persistence_sqla.alembic.env -> app.base.main.config.settings",
     "app.base.outbound.persistence_sqla.alembic.env -> app.base.main.modules",
   ]

   # Today's clean-architecture contract, unchanged apart from the prefix.
   [[tool.importlinter.contracts]]
   id = "clean-architecture"
   type = "layers"
   containers = ["app.base"]
   layers = ["(main)", "inbound", "outbound", "core"]
   ignore_imports = [ "app.base.outbound.persistence_sqla.alembic.env -> app.base.main.config.loader", "..." ]
   ```
   `alembic/env.py` keeps today's two exceptions to the composition root, plus one new one, to read the registered units' table mappings. A test also proves `src/app/` holds only `base/`, `modules/` and `shared/`.
2. **The same layers inside every module and inside `shared`.**
   ```toml
   [[tool.importlinter.contracts]]
   id = "unit-layers"
   type = "layers"
   containers = ["app.modules.*", "app.shared"]
   layers = ["(main)", "(inbound)", "(outbound)", "(core)"]
   exhaustive = true
   ```
3. **Modules depend on each other one way only.**
   ```toml
   [[tool.importlinter.contracts]]
   id = "module-order"
   type = "layers"
   containers = ["app.modules"]
   layers = ["notifications", "organizations"]
   exhaustive = true
   ```
4. **Across the boundary, each layer reaches only the same or a lower `base` layer.**
   ```toml
   [[tool.importlinter.contracts]]
   id = "module-core-uses-base-core-only"
   type = "forbidden"
   source_modules = ["app.modules.*.core"]
   forbidden_modules = ["app.base.inbound", "app.base.outbound"]

   [[tool.importlinter.contracts]]
   id = "outbound-not-base-inbound"
   type = "forbidden"
   source_modules = ["app.modules.*.outbound", "app.shared"]
   forbidden_modules = ["app.base.inbound"]
   ```
   A module's `core/` imports only `src/app/base/core/` (and other modules' `core/api.py`); its `outbound/` imports `src/app/base/outbound/` and `src/app/base/core/` (so `sqla_organization_reader.py` keeps joining `users_table`); its `inbound/` imports `src/app/base/inbound/`, `src/app/base/outbound/` and `src/app/base/core/`; its `main/` imports any `base` layer except `src/app/base/main/` (rule 1). `shared` imports `src/app/base/core/` and `src/app/base/outbound/` only.
5. **Internals are private** (one contract per unit):
   ```toml
   # Other modules see only Organizations' core/api.py.
   [[tool.importlinter.contracts]]
   id = "organizations-internals"
   type = "protected"
   protected_modules = [
     "app.modules.organizations.core.common", "app.modules.organizations.core.commands",
     "app.modules.organizations.core.queries", "app.modules.organizations.inbound",
     "app.modules.organizations.outbound", "app.modules.organizations.main",
   ]
   allowed_importers = ["app.modules.organizations", "app.base.main"]

   # Nobody but the composition root imports shared (Step 5).
   [[tool.importlinter.contracts]]
   id = "shared-internals"
   type = "protected"
   protected_modules = ["app.shared"]
   allowed_importers = ["app.base.main"]
   ```
6. **The CQRS rules, in every unit and across the boundary.** Today's four CQRS contracts move to `app.base.core.*`; the same rules apply in every module (a module's `core/common/` may not import commands or queries, its own or `src/app/base/core/`'s; its commands may not import queries and its queries may not import commands, on either side). Organizations already obeys these (checked 2026-10-22). The existing `auth-ctx` contract moves to `app.base.outbound.auth_ctx` / `app.base.outbound.adapters`.

**The tests** (`tests/base/unit/architecture/`, unit level, so they run in `make check`, and every new rule is a normal RED/GREEN cycle; `agents.md` 2.2 requires a RED to be a running test failure, which `lint-imports` alone can't show). They read the contracts from `pyproject.toml` with `importlinter.api.read_configuration()` and run them through import-linter's `Contract.check()`, so the rules exist in one place:
- **each contract catches what it should:** against a small fake graph built with `grimp.ImportGraph()` (as `tests/unit/main/wiki_tools/test_dependency_graph.py` already does), containing exactly one forbidden import, the contract reports it broken. No application code is changed to prove it (finding 3);
- **the real code obeys every contract:** against the real `app` import graph, every contract is kept;
- **no unit is left out:** every unit in the registry is covered by rules 2, 3, 5 and 6.

`lint-imports` keeps running in `make check` for its readable output. **What the rules can't see:** DI wiring, run-time needs (Notifications and `base` needing `shared`), shared tables (the foreign keys into `users.id`), event names stored as strings in the outbox. The registry's start-up checks, the container characterisation tests and the feature-delete test cover those.

### Settings

The settings classes stay in `src/app/base/main/config/settings.py` (Decision 5), except two: `OrganizationSettings` moves to `src/app/modules/organizations/main/config/settings.py` (Decision 14) and `EmailSettings` to `src/app/shared/main/config/settings.py` (Decision 15), because rule 1 forbids units from importing `src/app/base/main/`. Their loaders stay in `src/app/base/main/config/loader.py`. The loader test `test_load_organization_settings_reads_env_vars` (in `tests/base/unit/main/config/test_loader.py` after Step 2) changes only an import. `test_loader.py` has no loader test for `EmailSettings` today (checked 2026-10-22): a gap against `agents.md` 2.3, recorded here and not fixed during this plan (ground rules: known issues are fixed separately).

### Tests and commands

- **Tests follow the mirroring rule** (Decision 10), unit first, which under Option B mirrors `src/` exactly:
  ```
  tests/base/<path>                                   ← tests/<path> (Step 2: every test that stays with the original app)
  tests/modules/organizations/<path>                  ← tests/<path> (Step 4), e.g.
      tests/modules/organizations/unit/core/commands/organizations/test_invite_organization_member.py
  tests/modules/notifications/unit/core/common/events/handlers/... ← tests/unit/core/common/events/handlers/ (Step 3)
  tests/shared/<path>                                 (Step 5, if the email adapters gain tests)
  tests/base/unit/architecture/                       (new, Step 1)
  ```
  Whole-app suites stay with `base`, because the whole app is put together in `src/app/base/main/`: `tests/base/characterisation/`, `tests/base/sanity/`, `tests/base/smoke/`, `tests/base/integration/migrations/`.
- **Shared fixtures in module tests.** pytest applies a `conftest.py` only below its own folder, so each module's infrastructure tests get a `conftest.py` (for example `tests/modules/organizations/integration/with_infra/conftest.py`) that imports every shared fixture they use, and every fixture those depend on, from `tests/base/integration/conftest.py` and `tests/base/integration/with_infra/conftest.py`, including the autouse `it_worker_runtime`, so module tests run exactly like base tests.
- **Test helpers shared across the boundary.** Module tests may import `base`'s test helpers (as module code imports `base`). Two `base` tests import a module's test helper today and need a decision (O5): `tests/unit/core/commands/users/test_update_user_profile.py:26` and `tests/unit/outbound/auth_ctx/handlers/test_update_own_profile.py:22` import `NOW` from `tests/unit/core/commands/organizations/factories.py`.
- **Files whose unit needs a decision at their move step** (`agents.md`: "a file whose module is unclear is a question for the human maintainer, not a guess"): `tests/integration/with_infra/api_keys/test_organization_reads.py` (tests Organizations' public routes but uses `it_public_client` from `tests/integration/with_infra/api_keys/conftest.py`) and `tests/integration/with_infra/organizations/test_invitation_email_worker.py` (tests a Notifications handler in the worker container).
- **`make check` and `make test-docker` still run everything:** their path lists become `tests/base/...` plus each module's and `shared`'s matching folders (Make's `$(wildcard tests/modules/*/unit)` and so on), changed in Step 2 and extended as units arrive.
- **Per-module commands** (O6, closed 2026-11-13): one Makefile variable naming the unit, `unit=` (for example `unit=organizations`, `unit=base`, `unit=shared`), running that unit's light tests locally and its infrastructure tests in the Docker test stack. An unknown name, or a unit with no tests for that run, stops make before pytest runs. The linters (ruff, mypy, lint-imports) still run over everything: boundary rules are about the whole graph. Tested per Decision 7.

### Things to think about: what stays single for now

Practical compromises, accepted for now and revisited later (human maintainer, 2026-10-17):
- **Alembic migrations:** one history for every unit (finding 8), at `src/app/base/outbound/persistence_sqla/alembic/`. A module can be removed from the code, but its tables and migrations stay.
- **The SQLAlchemy mapper registry and `MetaData`:** one, in `src/app/base/outbound/persistence_sqla/registry.py`. Each module contributes only its own mapping functions.
- **The database:** one database and one schema, table names unchanged.
- **The event outbox:** one shared `event_outbox` table in `base`.

### Asking the original author

The human maintainer will ask the original author (https://github.com/ivan-borovets) for his view on the layout **after** it is built and tested on the branch, "to know my story before reaching out". If he advises keeping his layers at the top of `src/app/` (Option A, the layout this plan had on 2026-10-22), moving back is the same mechanical step in reverse (drop the `base/` prefix and restore the entrypoint paths and `parents[4]`); the modules, registry, rules and tests carry over. His answer is recorded here next to Decision 17.

## Decisions for the human maintainer

1. **Migrations: one Alembic history** (decided 2026-10-17, see "Things to think about"). Recorded here for completeness.
2. **How a module is registered and deregistered.** **Decided: (a)**, by the human maintainer, 2026-10-21. Recommended **(a)**: a code list in `main/modules.py` (python-ddd, lato). **(b)** a setting such as `ENABLED_MODULES` (evolutionary-architecture's per-module flags) is more flexible but is a new setting (with its loader test, `agents.md` 2.3) and lets a misconfiguration switch off a required module, so it needs the dependency check at start-up either way. (a) can grow into (b) later. *Under Option B the list is `src/app/base/main/modules.py` and also registers `shared`.*
3. **Outbox rows and Celery messages in flight across the deploy.** **Decided: (c) nothing**, by the human maintainer, 2026-10-30, replacing (b), decided 2026-10-21: no mapping and no deploy procedure; rows and messages written before a move are simply not delivered after it. The human maintainer's words: "Remember that this code is early in development. We keep changing tables and the relations via migrations. We keep removing and recreating docker volumes. We should not care about temporary things like draining the table. This seems like unnecessary complexity", and "During active pre-launch development (before version 1.0.0. We should not make permanent code changes to accommodate temporary complexity from requiring rows to survive an upgrade until this code is ready for that" (recorded in `docs/plans/agents.md` 4.8). The first commit's CHANGELOG entry says so in one line. The options as first weighed, kept as history: both carry the event's and the handler's import path (`HybridEventDispatcher` stores `dotted_path(type(event))` and `dotted_path(type(handler))`; the worker resolves them with `import_from_dotted_path`). Moving those classes orphans anything created before the deploy. **(a)** A deploy procedure only: stop the web app, let the worker drain the outbox and the queue, then deploy. No code, but every fork must follow it. **(b) Recommended:** a small, test-first mapping from the old paths to the new ones inside `import_from_dotted_path`, kept for one release and then removed (a dated follow-up), so no fork can lose an email by deploying normally. *Under Option A (2026-10-22) the mapping covered three classes. Under Option B (2026-10-23) every class moves in Step 2, so it covers four: `UserRegisteredEvent`, `OrganizationInvitationCreatedEvent`, `SendWelcomeEmail` and `SendOrganizationInvitationEmail`, from their v0.19.1 paths to their paths at the first commit, and it lands in Step 2 (O3).*
4. **Integration events.** **Decided: as recommended**, by the human maintainer, 2026-10-21. Recommended: keep today's event classes as the public contract, exposed through each module's public API (`core/api.py` under Decision 13's proposal). kgrzybek's separate integration-event types (domain events kept private, small translated events published) add a type and a translation per event; worth it only when an event's internals start leaking. Revisit with the first fork module.
5. **Settings:** **Decided: as recommended**, by the human maintainer, 2026-10-21. Recommended to stay in `main/config/` for now (no loader-test churn); a module could own its settings classes later. *Amended by Decisions 14 and 15 for `OrganizationSettings` and `EmailSettings` only; under Option B the file is `src/app/base/main/config/settings.py`.*
6. **The CLI's place.** **Decided: as recommended**, by the human maintainer, 2026-10-21: the CLI's plumbing stays in `main/cli/` and only the user commands move into Identity. *Superseded by Decision 9 (2026-10-22): Identity stays in the original app, so the whole CLI stays (at `src/app/base/main/cli/` under Option B) and no module has CLI commands yet; this decision applies again when Identity moves.*
7. **Testing the new Makefile targets.** They are shell, with no automated tests, like `OPEN_DASHBOARDS`. Under `agents.md` 2.1, "not worth an automated test" is the human maintainer's call: human checks only, or a small pytest that runs them through `make -n` and checks the paths they select. **Decided: the small pytest through `make -n`**, test-first, plus human checks (human maintainer, 2026-10-21: "We should follow RED/GREEN Test Driven Development (TDD) cycles"). *The AI agent chose this option from that instruction; the human maintainer confirmed it on 2026-11-04 (O8).*
8. **Roadmap item "group `core/commands/` and `core/queries/` by area".** This plan supersedes it: grouping by module does that and more. Recommended: mark it superseded when this plan ships. **Decided: as recommended**, by the human maintainer, 2026-10-21. *Under this plan only Organizations' files leave those folders; Identity's stay flat until Identity becomes a module, so whether the roadmap item is superseded or only shortened is O9.*
9. **Only Organizations and Notifications become modules; the original author's code keeps its shape.** **Decided** by the human maintainer, 2026-10-22: "Lets go with option A and we can always move towards option B if Ivan responds." Identity, API keys, the public API's entrypoint, the CLI, the worker and the admin use cases stay in the original app ("We will keep admin use cases in base because it was part of the original/upstream code anyway"); Identity can move into a module once this structure has proven itself. Considered and set aside: every bounded context as a module with a shared kernel and a platform module (the earlier version of this plan, too much moving at once). *The layout part (Option A: the original layers left at the top of `src/app/`) is superseded by Decision 17 (2026-10-23); the scope stands.*
10. **The mirroring rule.** **Decided** by the human maintainer, 2026-10-22: a moved file's path is `src/app/modules/<name>/` + its path below `src/app/` today, with the same folder and file names, because folder names carry meaning ("they are not just folders"). Tests follow the same rule. Alembic stays an outbound concern at `src/app/outbound/persistence_sqla/alembic/`. *Under Option B (Decision 17) the rule applies to every unit: `src/app/base/`, `src/app/modules/<name>/` and `src/app/shared/`, each + the path below `src/app/` today; Alembic stays outbound, at `src/app/base/outbound/persistence_sqla/alembic/`.* *Amended by the human maintainer, 2026-11-09, for Organizations' routes only:* they go to `src/app/modules/organizations/inbound/http/private_api/` (the cookie app's, under `/api/v1`) and `src/app/modules/organizations/inbound/http/public_api/` (the API-key app's, under `/public/v1`), with no `organizations/` folder below them, because a reader clicking through nested folders all named `organizations` can't tell what each one means. The human maintainer's words: "Things being mirrored should not come at the cost of file organization communicating architecture semantically. The folder structure and file locations have meaning." Mirroring stays the default and the safety measure; only the human maintainer decides an exception, case by case. A bigger module (Identity) may get its own shape when it moves.
11. **The six import rules, tested.** **Decided** by the human maintainer, 2026-10-22 ("the import should maintain the same boundaries at each module and we should have tests to ensure this"; "your linter explanation works"): the contracts under "Import rules", each tested against a fake graph and the real graph, with the module list taken from the registry. *Rewritten for Option B by Decision 17.*
12. **The public API is an entrypoint, not a module.** **Decided** by the human maintainer, 2026-10-22: its entrypoint and Identity's public routes stay in the original structure; Organizations' public routes move into the Organizations module, beside its private routes, and are registered through the registry.
13. **A unit's interface:** `main/module.py`, `main/ioc/` and `main/config/settings.py` for how it plugs into the app; `core/api.py` for what other modules may use; the unit contract as a `Protocol` in `src/app/base/main/` that units satisfy without importing it. **Decided** by the human maintainer, 2026-11-03 (O7), over the alternative of a dataclass in `src/app/base/main/modules.py` that the registry fills in for each unit. Why: with the `Protocol`, each module describes itself next to its own code (what it needs, its providers per entrypoint, its subscriptions), as in kgrzybek's per-module `MeetingsStartup`, evolutionary-architecture's per-module registration called from `ModulesRegistry`, lato's `ApplicationModule` and Django's `AppConfig`. A registry-built dataclass would make `src/app/base/main/modules.py` know every module's internals and grow with every module, the drift of finding 2. Costs accepted: every unit defines every name, even an empty one (a `Protocol` has no module-level defaults; mypy flags a unit that forgets), and the registry's start-up checks, not the type, validate the values.
14. **`OrganizationSettings` moves into the Organizations module.** **Decided** by the human maintainer, 2026-10-22 ("sounds good"): to `src/app/modules/organizations/main/config/settings.py`; the loader stays in the composition root's `config/loader.py` (`src/app/base/main/config/loader.py` under Option B).
15. **Email moves into `shared`, after Organizations and Notifications.** **Decided** by the human maintainer, 2026-10-22: "we need to test if this will work so lets add email in shared as a follow up in the same plan. We will get to it after organisations and notifications are done." The email transport is ours (`docs/plans/1-events.md`), not the original author's, and is domain-free, so it tests whether a unit of shared code works. The AI agent had recommended deferring it to a later plan and naming the module `platform`, because "shared" invites a junk drawer of anything without a clear home; the rule for `shared` is therefore no business meaning, checked by the import rules and by review. **Amended the same day** after working it through against plans 11 and 12 ("What goes where", recommended by the AI agent, accepted by the human maintainer): the `EmailSender` port stays in the original app and only its implementations, settings and bindings move, so the error alerting is unaffected (O11 closed), and `shared` is required by `base`. *Placed at `src/app/shared/`, a top-level unit, by Decision 17.*
16. **Commit once Organizations and Notifications work, before starting `shared`.** **Decided** by the human maintainer, 2026-10-22: "we should commit after organizations and notifications modules are working so that we started the shared module knowing the other 2 are fine." This amends the working method's single commit (`agents.md` 1.4: "unless the human maintainer says otherwise"). *With Option B's extra step (2026-10-23): the first commit closes Steps 0 to 4 (including the move into `src/app/base/`), after their human checks pass, with its own release bookkeeping; the second closes Steps 5 to 8.* *Amended 2026-11-11 by the human maintainer: Step 4's human checks run at the end of the plan, together with Steps 5 to 8's, and the plan closes with a single commit. For now, a brief smoke check after Step 4g stood in for them: a fresh `make upd`, then the seeded organizations read through the public API (`"total": 4`). The human maintainer's words: "Human checks are so involved and time consuming that I prefer to do them at the end of the modular monolith plan before committing."*
17. **Option B: three top-level units, `src/app/base/`, `src/app/modules/` and `src/app/shared/`.** **Decided** by the human maintainer, 2026-10-23: "Since we have core, inbound, main, outbound, it really does not make sense to put modules as a parallel directory ... it will create too much semantic noise. Its a design conflict with the semantic and code enforced boundaries of those very clear layers. Clear layers actually reduces cognitive demand by making it easy to identify where code should go." Then: "Yeah option B is better", and, asked whether `src/app/shared/` should be part of this plan with search and file storage coming: "Yes please update the plan so it uses option b with these dependencies." The original author's app moves into `src/app/base/` with nothing below the prefix changing; `shared` is a top-level unit rather than `src/app/modules/shared/`, so `modules/` holds bounded contexts only; the dependencies are those under "Dependencies". The AI agent's input: the costs are the entrypoint and tooling paths and one line of `src/app/base/main/config/loader.py` (`parents[4]` → `parents[5]`); "host", the .NET references' name for the composition root, would misname `base` (finding 14).

**Open questions** (raised 2026-10-22 and 2026-10-23, held until the human maintainer has finished exploring the design):
- **O1. Closed (2026-11-03): Notifications first**, as recommended, by the human maintainer. The question was the order of the module steps. Recommended: after the move into `src/app/base/` (Step 2), Notifications first (the smallest module, and it exercises the registry, every entrypoint's container, events, the worker and the feature-delete test), then Organizations. The alternative is Organizations first.
- **O2. Closed (2026-10-24): strict.** The human maintainer: "Lets be very strict. The friction is worth it." Both OpenAPI documents, as served at `/openapi.json` and `/public/openapi.json`, equal committed JSON text exactly (key order is what Swagger shows); each container's ports pinned to their concrete classes, as unit tests with literal settings so they run in `make check`; the test counts frozen after Step 0.
- **O3. Closed (2026-10-30).** The question was when the old-path mapping (Decision 3) would land. No mapping is built: Decision 3 is now (c).
- **O4. Closed (2026-10-23).** Test grouping follows the mirroring rule under Option B: unit first (`tests/base/`, `tests/modules/<name>/`, `tests/shared/`).
- **O5. Closed (2026-11-09): `base` gets its own `NOW`**, as recommended, by the human maintainer, so deleting Organizations never breaks a `base` test. The question was whether the two `base` tests importing `NOW` from Organizations' test helpers (see "Tests and commands") keep that import.
- **O6. Closed (2026-11-13): `unit=<name>` on the existing targets**, by the human maintainer. The question was what to name the per-module commands (`make check module=organizations` or separate targets; `module=base`, `module=shared`). Set aside: `module=`, which misnames `base` and `shared`, since neither is a module; and separate `test-<unit>` targets, whose pattern would clash with `test-docker*`.
- **O7. Closed (2026-11-03): the `Protocol`.** The question was Decision 13's proposal for a unit's interface; Decision 13 records the choice and why.
- **O8. Closed (2026-11-04): Decision 7's option confirmed** by the human maintainer: the Makefile's behaviour is tested by a small pytest through `make -n`. The Docker test image has no `make` (checked 2026-11-04), so these tests carry a `skipif` with its reason: `make check` runs them on the host, and `make test-docker` reports them as skipped. Considered and set aside: a separate test folder kept out of the Docker run (more Makefile restructuring), and installing `make` in the image (a change to the original author's Dockerfile).
- **O9. Closed (2026-11-14): superseded**, as Decision 8 recommended, by the human maintainer. The question was what happens to the roadmap item in Decision 8. The README's and the roadmap's "group `core/commands/` and `core/queries/` by area" item is struck through as superseded, and a new item, Identity as a module, holds what remains: Identity's files stay flat until Identity moves.
- **O10. Closed (2026-11-14): accepted**, as recommended, by the human maintainer. Every moved module's logger (`logging.getLogger(__name__)`) gets a new name, and under Option B that is all of them (about 43 modules), which shows in the JSON logs' `logger` field. The 0.20.0 `CHANGELOG.md` entry records it.
- **O11. Closed (2026-10-22).** The question was how the error alerting (`src/app/inbound/http/errors/exception_middleware.py`, lines 12 and 151) keeps sending email once email moves. Resolved by "What goes where": the `EmailSender` port stays in the original app, so the alerting's import doesn't change.

## Proposed changes

### Working method (decided by the human maintainer, 2026-10-21)

- **Two commits** (`docs/plans/agents.md` 1.4; amended from one by Decision 16, 2026-10-22): the first once the move into `src/app/base/`, Notifications and Organizations work (Steps 0 to 4), the second at the end (Steps 5 to 8), each after its human checks pass. *Amended 2026-11-11 (Decision 16's amendment): one commit at the end of the plan, after the human checks of Steps 4 to 6.*
- **The app works after every step.** In the human maintainer's words: "I should be able to test and run the app after each restructuring step and the app should work as it does now." So every step, move or new code, ends with `make check` and `make test-docker` green and the same counts, then a short human check: `make upd`, and a few `curl` requests with a read-back through the areas that step touched. A step too big to stay runnable is split into smaller sub-steps that each are.
- **RED/GREEN TDD** for every piece of new code (`agents.md` 2.1). Pure moves add no behaviour; the Step 0 characterisation tests and unchanged test counts prove them.
- **Every change is shown as a diff before it is made** (`agents.md` 1.5): new files and folders through Write, import changes through Edit. File moves are `git mv` commands the human maintainer runs, so git keeps each file's history; the import fixes that follow are Edit diffs.
- **Thin, cross-cutting tests early; the existing suite as the thick layer** (human maintainer, 2026-10-22: "Its better to discover bad design choices earlier than later ... even if it means developing thin system cross cutting tests early and larger thicker tests later"). The characterisation tests and the import-boundary tests come first; the existing 852 tests run after every step.

Every move step follows the same discipline: before it, record `make check` and `make test-docker` counts; move one area **with its tests**; update imports, the import-linter contracts and the paths in `pyproject.toml` and elsewhere that name it; then `make check` and `make test-docker` must show the same counts, all green, and the characterisation tests from Step 0 must still pass. A move step adds no behaviour. Every step that adds code is RED first, then GREEN (`agents.md` 2.1).

The order of Steps 3 and 4 follows O1 (closed 2026-11-03: Notifications first).

0. **Preconditions and characterisation tests.**
   - On the branch `feature/modular-monolith`, from v0.19.1 (`22d8e16`), with plan 14 parked on `wip/row-level-security`; `git status` clean apart from this plan; `make check` and `make test-docker` green; counts recorded here.
   - **Baseline, recorded 2026-10-23 at `22d8e16`** (before the characterisation tests):
     - `make check`: linters clean, then `549 passed, 5 deselected` (`tests/sanity`, `tests/unit`, `tests/integration/no_infra`; coverage 73%).
     - `make test-docker`: `843 passed, 5 deselected` in the app suite (the light paths plus `tests/smoke` and `tests/integration/with_infra`; coverage 94%), then `9 passed` in the migrations suite (`tests/integration/migrations/test_stairway.py`, one per revision).
     - 843 + 9 = 852, the number `pytest --collect-only` collects; the 5 deselected are the `slow` bcrypt tests.
   - Characterisation tests, written before anything moves, that pin today's behaviour so every later step proves it unchanged. They pass on day one (confirmation tests, said so explicitly); their strictness is O2. They live in their own suite folder, `tests/characterisation/` (mirroring `src/app/` below it, and part of `make check`'s light paths), so a reader can tell from the tree that they record behaviour rather than drive it (human maintainer, 2026-10-24):
     - both OpenAPI documents (the web app's and the public API's) equal a committed snapshot;
     - each of the four DI containers builds, and resolves every command, query and handler it resolves today, each port to the same concrete class;
     - the event subscriptions are exactly today's, per entrypoint (web: UserRegistered → SendWelcomeEmail, OrganizationInvitationCreated → SendOrganizationInvitationEmail; CLI: UserRegistered → SendWelcomeEmail);
     - the mapped tables are exactly today's six;
     - the CLI command list is exactly today's.
   - **Baseline with the characterisation tests, recorded 2026-10-28** (the counts O2 freezes; Step 1 adds its boundary tests on top, and the counts after Step 1 are the ones Step 2 must reproduce):
     - `make check`: linters clean, then `671 passed, 5 deselected` (549 + the 122 characterisation cases; coverage 78%).
     - `make test-docker`: `965 passed, 5 deselected` in the app suite (843 + 122; coverage 94%), then `9 passed` in the migrations suite.
     - 965 + 9 = 974 tests. The 122 characterisation cases are 2 OpenAPI snapshots, 118 container cases (bindings, absent bindings, email senders, event subscriptions), 1 mapped-tables case and 1 CLI command-tree case.
1. **The import-boundary tests for today's contracts.** `tests/unit/architecture/` (`tests/base/unit/architecture/` after Step 2) runs today's contracts (`clean-architecture`, the four CQRS contracts, `auth-ctx`) against the real graph and against one fake violation each. Confirmation tests: they pass on day one, and from then on each new contract is added RED first.
   - **Done 2026-10-28:** `tests/unit/architecture/test_import_contracts.py`, 13 tests (every contract has a forbidden-import case; the real code keeps each of the six; one forbidden import breaks each of the six).
   - **Baseline after Step 1** (the counts Step 2 must reproduce): `make check` `684 passed, 5 deselected`; `make test-docker` `978 passed, 5 deselected` in the app suite, then `9 passed` in the migrations suite (987 tests).
2. **The original app into `src/app/base/`** (Decision 17; a pure move, in runnable sub-steps):
   - 2a: `git mv` `src/app/{core,inbound,outbound,main}` into `src/app/base/` and `tests/{characterisation,integration,performance,sanity,smoke,unit}` into `tests/base/`; every `app.` import becomes `app.base.`; every path listed under "What changes in place" (entrypoints, `README.md` line 74 for approval, scripts, `alembic.ini`, `pyproject.toml`, the `Makefile`, `loader.py`'s `parents[5]`); the contracts move to `app.base` and `unit-order` is added (RED first: its test);
     - **Done 2026-10-29:** the move, every path update (`README.md` lines 28, 74, 75 and 101 approved by the human maintainer), and `unit-order`, RED first (3 failed, 12 passed), then GREEN (15 passed). Two changes from the contract under "Import rules": `app.modules` and `app.shared` are optional layers (`"(app.modules)"`, `"(app.shared)"`) until they become packages, because import-linter reports a missing layer as an error; and the third `alembic/env.py` exception (`-> app.base.main.modules`) is added with the registry in Step 4, because import-linter also reports an ignored import that matches nothing. Counts after 2a: `make check` `686 passed, 5 deselected`, 7 contracts kept; `make test-docker` `980 passed, 5 deselected`, then `9 passed` (989 tests). These are the counts 2b and 2c build on.
   - 2b: dropped on 2026-10-30 (Decision 3 is now (c): no old-path mapping before 1.0.0);
   - 2c, RED/GREEN: `scripts/wiki/dependency_graph.py` learns `app.base.<layer>`, with its tests extended so the real-graph check isn't vacuous;
     - **Done 2026-11-03:** RED first (2 failed, 4 passed), then GREEN (6 passed). `_layer_of()` reads the layer only from names under `app.base`. The real-graph test now also requires three edges that exist in the code today (`main → inbound`, `inbound → core`, `outbound → core`), so it can't pass on an empty graph. The fixture line the prefix pushed past 120 characters was wrapped afterwards, in its own approved formatting step. Counts unchanged: `make check` `686 passed, 5 deselected`, 7 contracts kept; `make test-docker` `980 passed, 5 deselected`, then `9 passed`.
   - the tests that pin moved paths change with them (`test_event_serialization.py`, `test_dependency_graph.py`'s alembic pins, the two logger-name tests).
   - Human checks: `make upd`; log in and read back the profile; sign up and see the welcome email in the worker's log (the worker resolving moved classes); `make cli args="users list"` (the CLI's new module path); open `/docs` and `/public/docs`.
3. **The registry and Notifications** (the first module, end to end):
   - RED/GREEN: the unit contract and the "needs" check; the registry building each entrypoint's providers and event subscriptions;
     - **Progress, 2026-11-04:** three cycles done, each RED first.
       - The "needs" check: `src/app/base/main/modules.py` holds `Unit` (a `Protocol` with `NAME` and `NEEDS`), `MissingUnitError` and `check_needs`, tested in `tests/base/unit/main/test_modules.py` (RED: 1 error, the module didn't exist; GREEN: 2 passed).
       - Combining subscriptions: `Subscriptions` and `collect_subscriptions` in the same file (RED: 1 error; GREEN: 5 passed). A later unit's handlers are added after an earlier one's for the same event, never replacing them; no units gives no subscriptions.
       - The `Makefile`'s `PYTEST_PATHS_LIGHT` and `PYTEST_PATHS_APP_INFRA` pick up `tests/modules/*/unit` and `tests/modules/*/integration/with_infra` by wildcard (user story 5; planned for Step 2 under "Tests and commands", done here), tested through `make -n` in `tests/base/unit/main/test_makefile_test_paths.py` (RED: 2 failed; GREEN: 2 passed; skipped in Docker, which has no `make`, O8).
       - Counts: `make check` `693 passed, 5 deselected`, 7 contracts kept. The full `make test-docker` runs at the end of Step 3 (`docs/plans/agents.md` 1.3).
       - Order changed for the rest of Step 3 (2026-11-04): the two handlers move before Notifications' `main/module.py` is written, so the module's subscriptions name its own handlers rather than `base`'s.
     - **Progress, 2026-11-05:** the handlers moved, Notifications registered, and the registries built from the registry.
       - The two handlers and their tests moved with `git mv` to `src/app/modules/notifications/core/common/events/handlers/` and `tests/modules/notifications/unit/core/common/events/handlers/`, with only their import paths changed; the import order the move upset was fixed afterwards, in its own approved formatting step. `test_invitation_email_worker.py` stays in `base` (it tests the worker container). Counts unchanged: `make check` `693 passed, 5 deselected`, and `make test-docker-file` on the affected integration tests `67 passed`.
       - Notifications describes itself in `src/app/modules/notifications/main/module.py` (`NAME`, `NEEDS`, `WEB_SUBSCRIPTIONS`, `CLI_SUBSCRIPTIONS`), and `UNITS` in `src/app/base/main/modules.py` lists it (RED: 1 error, `UNITS` didn't exist; GREEN: 8 passed). `make check` `696 passed, 5 deselected`, 7 contracts kept.
       - `CoreProvider` and `CliProvider` build their handler registries from `UNITS` through `collect_subscriptions`, asking dishka's container for each subscribed handler class. A refactor under green tests, with no RED: `test_the_event_subscriptions_are_todays` already pins each entrypoint's subscriptions, in order. Cost accepted: dishka no longer checks at build time that a subscribed handler is bound; the characterisation tests resolve every registry and every handler binding instead. `make check` `696 passed, 5 deselected`, 7 contracts kept; `make test-docker-file` on sign-up, admin create-user, invitations and the CLI suite `61 passed`.
       - Notifications binds its own handlers. `src/app/modules/notifications/main/ioc/providers.py` holds one provider per entrypoint that runs them (web, CLI, worker), tested in `tests/modules/notifications/unit/main/ioc/test_providers.py` (RED: 1 error; GREEN: 4 passed). The `Unit` Protocol gained `WEB_PROVIDERS`, `CLI_PROVIDERS` and `WORKER_PROVIDERS`, and `collect_providers` builds them in registration order (RED: 1 error; GREEN: 11 passed in `test_modules.py`). The three entrypoints add them through `collect_providers`, and `CoreProvider`, `CliProvider` and `WorkerProvider` no longer bind the handlers. That last change is a refactor under the characterisation tests (`BINDINGS`, `ABSENT`, the subscriptions). `make check` `703 passed, 5 deselected`; `make test-docker-file` on sign-up, admin create-user, invitations, the invitation-email worker, the CLI suite and the Celery smoke tests `64 passed`.
       - Start-up check. `get_providers`, `get_cli_providers` and `get_worker_providers` take the units (default `UNITS`) and call `check_needs` before building anything. Each entrypoint therefore refuses to start when a registered unit needs one that isn't registered, and names both (user story 4). It is tested once per entrypoint in `test_modules.py` (RED: 3 failed, 11 passed; GREEN: 14 passed). The public API joins when it first reads the registry (Step 4). `make check` `706 passed, 5 deselected`; the same `make test-docker-file` run `64 passed`.
       - Import rule 2, `unit-layers`: every module under `app.modules.*` keeps the layers main, inbound, outbound and core, all optional and exhaustive. Added RED first in `test_import_contracts.py` (RED: 3 failed, 14 passed; GREEN: 17 passed). `src/app/shared/` joins in Step 5. `make check` `708 passed, 5 deselected`, 8 contracts kept.
     - **Progress, 2026-11-06:** import rule 3.
       - `module-order`: modules depend on each other one way only, Notifications above Organizations. Notifications listens to Organizations' invitation event; Organizations never imports Notifications, so Notifications stays removable (user story 4). The contract is exhaustive, so a new module must be placed in the order on purpose. `organizations` is optional until it moves in, in Step 4. Added RED first in `test_import_contracts.py` (RED: 3 failed, 16 passed; GREEN: 19 passed). The direction matches the north star's own architecture tests: `src/Tests/ArchTests/Modules/ModuleTests.cs` forbids each module from depending on the others, except its event handlers. `make check` `710 passed, 5 deselected`, 9 contracts kept.
       - Import rule 4, two `forbidden` contracts across the boundary between a module and `base`, each added RED first in `test_import_contracts.py`. Both use the `app.modules.*` wildcard in `source_modules`, so Organizations is covered once it moves in.
         - `module-core-uses-base-core-only`: a module's `core/` imports only `base`'s `core/` (ports, events, entities), never its `inbound/` or `outbound/` (RED: 3 failed, 18 passed; GREEN: 21 passed). `make check` `712 passed, 5 deselected`, 10 contracts kept.
         - `outbound-not-base-inbound`: a module's `outbound/` never imports `base`'s `inbound/`, but may use `base`'s `outbound/` and `core/`. No module has an `outbound/` yet, so on the real code it holds trivially until Step 4; the fake graph gained the allowed case (Organizations' reader joining `base`'s users mapping). `src/app/shared/` joins it in Step 5 (RED: 3 failed, 20 passed; GREEN: 23 passed). `make check` `714 passed, 5 deselected`, 11 contracts kept.
       - Import rule 6, CQRS in every module. The human maintainer chose to widen the four existing CQRS contracts rather than add four module copies, for long-term maintainability: each rule stays one contract spanning `base` and every module (`app.modules.*.core.<folder>` beside `app.base.core.<folder>` in both `source_modules` and `forbidden_modules`), so a module can't drift from `base`'s rules.
         - First, a refactor under green: `FORBIDDEN_IMPORTS` maps each contract to a list of forbidden imports, and `test_one_forbidden_import_breaks_the_contract` runs once per import, so a contract that spans several units proves every side it covers (23 passed, counts unchanged). Step 5 uses the same for `shared`'s side of `unit-layers` and `outbound-not-base-inbound`.
         - RED: each CQRS contract gained two module-side imports, Organizations' own and across the boundary into `base` (8 failed, 23 passed); GREEN: 31 passed. `make check` `722 passed, 5 deselected`, 11 contracts kept.
       - The feature-delete test (user story 4). `tests/base/integration/with_infra/main/test_app_without_notifications.py` builds the web app with no units registered: it starts, sign-up succeeds and stores the user, no outbox row is staged and no email is sent. `make_app` takes the units (default `UNITS`), and the fixture `it_units` in `tests/base/integration/with_infra/conftest.py` passes them in, so a test module can override it.
         - RED: 1 error (`make_app` had no `units`).
         - GREEN in two parts, with a run between. First `make_app` passes the units to `get_providers`: 1 failed, sign-up answered 500 with a `NoFactoryError` for `SendWelcomeEmail`, because `CoreProvider`'s handler registry still read `UNITS` while the providers came from the units given. Then `CoreProvider` takes the units and builds its registry from them, and `get_providers` passes it the same list: 1 passed.
         - `make check` `722 passed, 5 deselected`; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`.
       - The same rule for the CLI, at unit speed. `test_an_entrypoint_built_without_units_subscribes_no_handlers` in `test_modules.py` builds the web and CLI containers with no units and expects an empty handler registry. It uses `skip_validation=True`, because only the registry is resolved; each real container's whole graph is still validated by the characterisation and integration tests.
         - RED: 1 failed, 15 passed (`[cli]`, a `NoFactoryError` for `SendWelcomeEmail`). A first run failed for the wrong reason, dishka's build-time check asking for settings, and was fixed before the RED counted.
         - GREEN: `CliProvider` takes the units like `CoreProvider`, and `get_cli_providers` passes them: 16 passed.
         - `make check` `724 passed, 5 deselected`, 11 contracts kept; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`. The worker has no handler registry (it resolves each handler by its dotted path), so it needed no change.
       - The second feature-delete test the step asks for, a module whose dependency is unregistered refusing to start, is the start-up check above (`test_each_entrypoint_refuses_to_start_when_a_unit_needs_an_unregistered_one`, once per entrypoint).
       - End of Step 3: the Step 3 human checks passed (checks 1 to 5, under "Human checks"). Running them fixed the checks themselves: a wait on `/healthz/` after `make upd`, `curl -sS` so a failed connection says why, the fresh-stack commands inside Step 3, file edits marked as editor edits, and a read-back for every sign-up. Counts: `make check` `724 passed, 5 deselected`, 11 contracts kept; `make test-docker` `1017 passed, 2 skipped, 5 deselected` in the app suite (coverage 94%; the 2 skipped are the `make`-based tests the Docker image can't run, O8), then `9 passed` in the migrations suite.
   - RED/GREEN: `unit-layers`, `module-order` and rule 4 and 6 contracts, each with its test;
   - move the two handlers and their tests (`git mv`), register Notifications;
   - the feature-delete test: an integration test builds the app without Notifications; it starts, sign-up succeeds, no email is sent, and nothing else changes. A second test proves a module whose dependency is unregistered refuses to start.
   - Human checks: sign up and see the welcome email in the worker's log; invite a member and see the invitation email; `make cli args="users create-user ..."` and see the welcome email.
4. **Organizations**, in runnable sub-steps:
   - Order, top-down (found 2026-11-06): `unit-order` forbids `base`'s lower layers from importing a module, so the routes move first, then the adapters, then core. Moving core first would leave `src/app/base/inbound/http/organizations/`, `src/app/base/inbound/http/public_api/organizations/` and `src/app/base/outbound/persistence_sqla/mappings/all.py` importing the module, which breaks `lint-imports`. Each sub-step ends with `make check` green.
   - 4a: register Organizations (`main/module.py`, empty to start; `UNITS = (organizations, notifications)`; Notifications needs `organizations`; `module-order` without the parentheses);
     - **Progress, 2026-11-06:** 4a done, in three TDD cycles.
       - The registry lists Organizations first. `src/app/modules/organizations/main/module.py` gives its name and leaves every other name empty until its code moves in (4b to 4e), so registering it changes nothing at run time. `UNITS = (organizations, notifications)`: Organizations comes first because today's routers include it first, and Notifications needs it. RED: 1 failed, 15 passed; GREEN: 16 passed. `make check` `724 passed, 5 deselected`.
       - Notifications needs Organizations, whose invitation event it handles. `tests/modules/notifications/unit/main/test_module.py` registers Notifications alone and expects `MissingUnitError` naming both units. The import rules can't catch this, because a deregistered Organizations is still importable. RED: `DID NOT RAISE`; GREEN: 1 passed. `make check` `725 passed, 5 deselected`; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`.
       - `module-order` lists `organizations` as a required layer, without the parentheses. `test_every_registered_module_is_a_required_layer_in_module_order` in `test_import_contracts.py` checks that every registered unit is a required layer, so renaming or deleting a registered module's package breaks the contract instead of passing quietly. RED: 1 failed, 31 passed; GREEN: 32 passed. `make check` `726 passed, 5 deselected`, 11 contracts kept.
   - 4b: the private routes' wiring. The registry gains the web app's routers, and `make_v1_router` takes them from `base/main`;
     - **Progress, 2026-11-06 to 2026-11-09:** 4b done, in three TDD cycles.
       - `collect_routers` in `src/app/base/main/modules.py` combines each unit's routers in registration order, for both apps (RED: `ImportError`; GREEN: 18 passed). `make check` `728 passed, 5 deselected`.
       - Each unit supplies `make_web_routers(*, cookie_name)`: the `Unit` Protocol gained it, Organizations returned today's private router and Notifications none (RED: 1 failed, 18 passed, an `AttributeError`; GREEN: 19 passed). `make check` `729 passed, 5 deselected`.
       - `make_v1_router(*, cookie_name, module_routers)` no longer imports Organizations; `run.py` and the sanity `conftest.py` build the routers from the units, so an app built without a unit serves none of its routes. Tested in `tests/base/unit/inbound/http/test_api_v1_router.py` (RED: 2 failed, a `TypeError`; GREEN: 2 passed). The test first read `router.routes`, which in FastAPI 0.142 held no `APIRoute` for an included router's endpoints: its paths came back empty and the "no Organizations path" test passed on an empty list. It now reads the paths from the OpenAPI document and also checks that a `base` path is served. `make check` `731 passed, 5 deselected`; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`.
   - 4c: the public routes' wiring, the same way for `make_public_router`; then the private and public route folders move together, in one move (found 2026-11-09: two of `base`'s public routes import their request schemas from the private routes, so moving the private routes alone would make `base` import the module). The slice's tests move in 4e, once the code they test has moved;
     - **Progress, 2026-11-09:** 4c done, in two TDD cycles and the move.
       - Each unit supplies `make_public_routers()` (RED: 1 failed, 19 passed, an `AttributeError`; GREEN: 20 passed). The test compares exact paths from the OpenAPI document, because the public router has the private one's prefix and tag. `make check` `732 passed, 5 deselected`.
       - `make_public_router(*, module_routers)` no longer imports Organizations; `make_public_api_app` takes `units` (default `UNITS`), and the sanity `conftest.py` builds the public routers from the registry too. Tested in `tests/base/unit/inbound/http/public_api/test_router.py` (RED: 2 failed, a `TypeError`; GREEN: 2 passed). `make check` `734 passed, 5 deselected`; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`. The public API doesn't run the "needs" check yet: it joins when Organizations' public bindings move into its own provider (4e).
       - The move, with no RED: the private routes (13 files) to `src/app/modules/organizations/inbound/http/private_api/` and the public routes (3 files) to `src/app/modules/organizations/inbound/http/public_api/` (Decision 10's amendment). Only import paths and the comments naming them changed; the import order and wrapping ruff then asked for came as a separate, reviewed diff. No Python file names either old path. `make check` `734 passed, 5 deselected`, 11 contracts kept, both OpenAPI snapshots unchanged; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`. The slice's tests stay in `base` until 4e.
   - 4d: outbound. `map_tables` takes the units' mapping functions from its callers (`alembic/env.py` reads them from the registry), then the three adapters and the two mappings move together;
     - **Progress, 2026-11-09:** 4d done, in three TDD cycles and the move.
       - `collect_table_mappings` in `src/app/base/main/modules.py` combines each unit's table-mapping functions in registration order; `TableMapping` names their shape (a function that takes and returns nothing). Tested in `test_modules.py` (RED: 1 error, an `ImportError`; GREEN: 22 passed). `make check` `736 passed, 5 deselected`.
       - Each unit supplies `TABLE_MAPPINGS`: the `Unit` Protocol gained it, Organizations listed today's two mapping functions (still imported from `base`) and Notifications none (RED: 1 failed, 22 passed, an `AttributeError`; GREEN: 23 passed). `make check` `737 passed, 5 deselected`.
       - `map_tables(*, module_mappings)` maps `base`'s four tables, then only the module mappings its caller gives it, so `base`'s `outbound/` no longer imports Organizations. Every caller passes `collect_table_mappings(unit.TABLE_MAPPINGS for unit in UNITS)`, or the units its app was built with: the web app's lifespan (`make_lifespan(*, table_mappings)`, which the public API reuses), the CLI, the worker, Alembic's `env.py` and three tests. `env.py` reading the registry is the third `alembic/env.py` exception in `unit-order` and `clean-architecture` (planned in 2a), listed in `test_import_contracts.py`'s allowed imports. Tested in `tests/base/unit/outbound/persistence_sqla/mappings/test_all.py`, which runs itself as a separate process like the mapped-tables characterisation test (RED: 1 failed, the child's `TypeError`; GREEN: 1 passed). `make check` `738 passed, 5 deselected`, 11 contracts kept, the mapped tables unchanged; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`; `make test-docker` `1031 passed, 2 skipped, 5 deselected`, then `9 passed`.
       - The move, with no RED: the three adapters to `src/app/modules/organizations/outbound/adapters/` and the two mappings to `src/app/modules/organizations/outbound/persistence_sqla/mappings/`, mirroring `base`. Only import paths changed, plus the two comments in Organizations' `module.py` that named the old place; the import order and wrapping ruff then asked for came as a separate, reviewed diff. No code names the old paths. `make check` `738 passed, 5 deselected`, 11 contracts kept, the mapped tables unchanged; `make test-docker-file` on `tests/base/integration/with_infra` `290 passed`; `make test-docker` `1031 passed, 2 skipped, 5 deselected`, then `9 passed`. The adapters' integration tests stay in `base` until 4e.
   - 4e: core, `OrganizationSettings` and `core/api.py` with `OrganizationInvitationCreatedEvent` (Notifications switches to it); Organizations' bindings move into its own providers;
     - **Order and decisions, 2026-11-09** (human maintainer, on the AI agent's recommendations after an inventory): nothing in `base`'s `core/`, `inbound/` or `outbound/` imports Organizations' core or `OrganizationSettings`; only `base`'s `main/` and `scripts/seed_db.py` do. A module may not import `src/app/base/main/`, so the settings move before the providers.
       - First, in its own step: `tests/base/integration/with_infra/organizations/test_rls_spike.py` is deleted, not moved. It is plan 9's Step 9 experiment and tests no app code: it creates its own role and policy with raw SQL and rolls them back. The human maintainer: "Do we need this file test_rls_spike.py? We might as well delete it in this current branch. It has not place, serves no purpose?" Plan 14's parked branch, built and tested on its own, keeps its own copy. The counts drop by its 3 tests. The wiki's Organizations page cites it; at the first commit that citation points to plan 9, Step 9 instead.
       - 4e-1: `OrganizationSettings` to `src/app/modules/organizations/main/config/settings.py` (Decision 14), a pure move; `loader.py` stays in `base` and imports it from there.
       - 4e-2, RED/GREEN: Organizations' providers in `src/app/modules/organizations/main/ioc/providers.py`, one for the web app (the bindings from `CoreProvider`) and one for the public API (from `ioc/public_api.py`). The `Unit` Protocol gains `PUBLIC_API_PROVIDERS`, and `get_public_api_providers` takes the units and runs the "needs" check (deferred from 4c).
       - 4e-3: the core move, the 25 files under "What moves" to `src/app/modules/organizations/core/`, mirroring `base`. `core/api.py` comes in 4f, as its GREEN.
       - 4e-4: the slice's tests to `tests/modules/organizations/unit/` and `tests/modules/organizations/integration/with_infra/`, with the module `conftest.py`. `test_invitation_email_worker.py` stays in `base` (Step 3). `tests/base/integration/with_infra/api_keys/test_organization_reads.py` moves with them; the module `conftest.py` imports `it_public_client` from `base`'s `api_keys/conftest.py`. `base`'s two tests that borrow `NOW` get their own (O5).
     - **Progress, 2026-11-09 to 2026-11-10:** the spike deleted and 4e-1 to 4e-4 done.
       - The spike, deleted with `git rm`. `make test-docker-file` on `tests/base/integration/with_infra` `287 passed` (290 less its 3).
       - 4e-1, a move with no RED: `OrganizationSettings` to `src/app/modules/organizations/main/config/settings.py`; `loader.py`, `run.py`, `ioc/core.py`, `scripts/seed_db.py` and two characterisation tests import it from there. `make check` `738 passed, 5 deselected`; with_infra `287 passed`.
       - 4e-2, in three TDD cycles:
         - Organizations' providers in `src/app/modules/organizations/main/ioc/providers.py`: `OrganizationsWebProvider` (`CoreProvider`'s 15 Organizations bindings) and `OrganizationsPublicApiProvider` (the public API's 5). Tested in `tests/modules/organizations/unit/main/ioc/test_providers.py` (RED: 1 error, a `ModuleNotFoundError`; GREEN: 3 passed). `make check` `741 passed, 5 deselected`.
         - Organizations' `WEB_PROVIDERS` lists its web provider and `CoreProvider` drops the 15 bindings; `UserFinder` stays in `base`. Tested in `test_modules.py`: the registered units provide today's bindings, and a web app built without units binds none of Organizations' (RED: 2 failed, 22 passed; GREEN: 24 passed). `make check` `742 passed, 5 deselected`; with_infra `287 passed`.
         - The `Unit` Protocol gains `PUBLIC_API_PROVIDERS`; `get_public_api_providers(units)` runs the "needs" check deferred from 4c and adds each unit's public API providers; `PublicApiProvider` drops its 5 Organizations bindings and `make_public_api_app` passes its units (RED: 3 failed, 23 passed; GREEN: 26 passed). `make check` `744 passed, 5 deselected`; with_infra `287 passed` (a first run failed one login with a database `OperationalError` while the host was short of memory; the re-run passed).
       - 4e-3, a move with no RED: the 25 files under "What moves" to `src/app/modules/organizations/core/`, mirroring `base`. Only import paths changed (285 lines: the moved files, the module's adapters, mappings, routes and providers, Notifications, `scripts/seed_db.py` and the tests), plus three comment words that named the files' old neighbours; the import order and wrapping ruff then asked for came as a separate, reviewed diff (72 files). No code names the old paths, and nothing in `base`'s code imports Organizations. Notifications imports the event from its own module until 4f. `make check` `744 passed, 5 deselected`; with_infra `287 passed`; `make test-docker` `1034 passed, 2 skipped, 5 deselected`, then `9 passed`.
       - 4e-4, a move with no RED: the slice's tests (32 files) to `tests/modules/organizations/`, mirroring the code they test (human maintainer's decisions). The unit tests go under `unit/core/`, the commands' tests without the old `organizations/` folder, since the module's name already says it. The database tests stay together in `integration/with_infra/`, joined by `test_organization_reads.py` from `api_keys/`. `test_invitation_email_worker.py` stays in `tests/base/integration/with_infra/organizations/`: it tests that a worker can build an invitation email. The module's `conftest.py` imports, by name, the `base` fixtures its tests use. Only import paths changed, plus three comments that named old paths and one that named `CoreProvider`; the import order ruff then asked for came as a separate, reviewed diff (5 files). `base`'s two tests that borrowed `NOW` from Organizations' test helpers define their own (O5), so no `base` test imports a module's tests. `make check` `744 passed, 5 deselected`; with_infra `197 passed` in `base` and `90 passed` in the module (287); `make test-docker` `1034 passed, 2 skipped, 5 deselected`, then `9 passed`.
   - 4f: the `organizations-internals` contract, RED first: other modules may import only `app.modules.organizations.core.api`. RED: the real code breaks it, because Notifications imports the event's own module. GREEN: `core/api.py` exports `OrganizationInvitationCreatedEvent` and the types of its fields (`OrganizationId`, `OrganizationMembershipId`), and Notifications imports from it.
     - **Progress, 2026-11-10 to 2026-11-11:** 4f done, in one TDD cycle.
       - `organizations-internals` in `pyproject.toml`, a `protected` contract as import rule 5 gives it: only Organizations itself and `base`'s `main/` may import Organizations' `core/common/`, `core/commands/`, `core/queries/`, `inbound/`, `outbound/` and `main/`, so another module sees only `core/api.py`. `test_import_contracts.py` learns the `protected` type and gains the contract's forbidden import (Notifications' handler importing the event's own file), plus four allowed imports that put every protected package in the fake graph (RED: 1 failed, 33 passed; the real code broke the contract on Notifications' `main/module.py` and its handler). GREEN: `src/app/modules/organizations/core/api.py` re-exports `OrganizationInvitationCreatedEvent`, `OrganizationId` and `OrganizationMembershipId`, and Notifications imports the event from it (34 passed). The event class stays in its own file, so outbox rows name it by the same path as before. `make check` `746 passed, 5 deselected`, 12 contracts kept; `make test-docker` `1036 passed, 2 skipped, 5 deselected`, then `9 passed`.
   - 4g: each unit seeds its own development data, through the registry (human maintainer, 2026-11-11, on the AI agent's recommendation). Found while writing Step 4's human checks: `scripts/seed_db.py` builds the app with the registered units, then seeds organizations through Organizations' own classes. With Organizations deregistered and `SEED_DB_WITH_TEST_DATA=true`, those classes are never mapped, the seeding fails, and `docker-entrypoint.sh` (`set -e`) never starts the app. Seeding becomes part of a unit's interface, like `TABLE_MAPPINGS`: the `Unit` Protocol gains `SEEDS`, `collect_seeds` combines them in registration order, and `seed_db.py` seeds `base`'s users and API keys, then each registered unit's seeds, without importing any module. Registration order and the "needs" check make sure a unit's seeds run after the units it needs. RED/GREEN: `collect_seeds`; then `Unit.SEEDS` (Organizations lists its seed function, Notifications none), with Organizations' seed data moved to `src/app/modules/organizations/main/seed.py` in the same GREEN, since the test can only pass once the function lives in the module. The seeding itself is not tested (`docs/plans/agents.md` 2.1): Step 4's human checks run it through `make upd`. Step 4's human check 5 deregisters Organizations both ways: alone (the app refuses to start, naming Notifications' need), and with Notifications (the app starts and serves no organization routes).
     - **Progress, 2026-11-11:** 4g done, in two TDD cycles.
       - `collect_seeds` and the `Seed` Protocol in `src/app/base/main/modules.py`. A seed function takes keyword arguments only: the open session, the seeded users' ids by username, and the app's container (for a unit's own settings). Its `__call__` returns `Awaitable[None]`, so a unit can spell its `SEEDS` without importing `base/main/`. RED: 1 error (`ImportError`); GREEN: 28 passed; `make check` `748 passed, 5 deselected`.
       - `Unit.SEEDS`: Organizations lists `seed_organizations`, Notifications none. Organizations' seed data and helpers moved, unchanged apart from two comments, to `src/app/modules/organizations/main/seed.py`; `seed_organizations()` holds the lines `seed_db.py`'s `main()` ran for organizations. `scripts/seed_db.py` seeds `base`'s users and API keys, then runs every registered unit's seeds, and no longer imports Organizations. RED: 1 error (`ModuleNotFoundError`); GREEN: 29 passed; `make check` `749 passed, 5 deselected`. Seed files are left out of coverage, since they are never tested.
       - `make test-docker` `1039 passed, 2 skipped, 5 deselected`, then `9 passed`.
   - Human checks: create an organization, invite, accept, list members (private routes, with read-backs); list my organizations and members with an API key (public routes); the invitation email.
   **First commit** (Decision 16): *deferred on 2026-11-11 to the end of the plan, together with Step 4's human checks (Decision 16's amendment); what follows now describes the plan's single commit.* once Steps 0 to 4 are done and their human checks pass, commit on `feature/modular-monolith` with its release bookkeeping (`agents.md` 1.4): a `CHANGELOG.md` entry and version (including one line: outbox rows and queued Celery messages written before this version name classes by their old import paths and are not delivered after it, Decision 3), and the wiki pages that name moved paths (paths updated, prose kept per `agents.md` 3.3). `shared` starts only after this commit, knowing the first two modules are sound.
5. **Email's implementations into `src/app/shared/`** (Decisions 15, 16 and 17), following "What goes where":
   - RED/GREEN: `shared`'s registration and providers per entrypoint (web app, CLI, worker); the registry's "required by `base`" property, with a test that the app refuses to start without `shared` and names it; Notifications declaring that it needs `shared`, with its test; the `shared-internals` contract and `shared` in `unit-layers`, each with its test;
   - move the console and SMTP adapters, `EmailSettings` and their tests (see "What moves"); the `EmailSender` port stays in `src/app/base/core/common/ports/email_sender.py`, so the error alerting and Notifications keep their imports;
   - **Progress, 2026-11-11 to 2026-11-12:** Step 5's code done, in nine TDD cycles and two moves.
     - 5a, a move with no RED: `EmailSettings` to `src/app/shared/main/config/settings.py`. `make check` `749 passed, 5 deselected`.
     - 5b: `make test` and `make test-docker-app` run `tests/shared/`'s tests, as they do each module's (tested in `tests/base/unit/main/test_makefile_test_paths.py`). `make check` `751 passed, 5 deselected`.
     - 5c: `SharedEmailProvider` in `src/app/shared/main/ioc/providers.py`: one class for the web app, the CLI and the worker, since the binding is the same at each (human maintainer's choice). It binds `EmailSender` to the console or the SMTP adapter, as `EmailSettings.USE_CONSOLE` says. Tested in `tests/shared/unit/main/ioc/test_providers.py`. `make check` `753 passed, 5 deselected`.
     - 5d: `shared` registered: `src/app/shared/main/module.py`, and `UNITS = (shared, organizations, notifications)`. `base`'s providers drop their three email bindings. `make check` `756 passed, 5 deselected`; `make test-docker` `1044 passed, 4 skipped, 5 deselected`, then `9 passed`.
     - 5e: "required by `base`" is `base`'s own list, `BASE_NEEDS = ("shared",)` in `src/app/base/main/modules.py`, not something a unit declares. `check_needs` refuses to start without it at every entrypoint, naming it: "Base needs unit 'shared', which is not registered." `make check` `761 passed, 5 deselected`.
     - 5f: Notifications' `NEEDS` adds `shared` (RED: 1 failed, the error named `base`'s need instead of Notifications'; GREEN: 2 passed). `make check` `762 passed, 5 deselected`.
     - 5g: the `shared-internals` contract, `protected`: only `base`'s `main/` may import `app.shared` (RED: 4 failed, 33 passed; GREEN: 37 passed). `make check` `765 passed, 5 deselected`.
     - 5h: `shared`, as a whole, is a source in `outbound-not-base-inbound`: no layer of it may import `base`'s inbound, which `unit-order` alone would allow (RED: 1 failed, 37 passed; GREEN: 38 passed). `make check` `766 passed, 5 deselected`.
     - 5i, a move with no RED: the console and SMTP adapters to `src/app/shared/outbound/adapters/`. Only import paths changed; the adapters had no tests of their own to move. The console adapter's logger is now named after its new path; its messages are unchanged. `make check` `766 passed, 5 deselected`.
     - 5j: `unit-layers` covers `app.shared` too, so its `outbound/` can't import its `main/` (RED: 1 failed, 38 passed; GREEN: 39 passed). `make check` `767 passed, 5 deselected`.
     - 5k: `app.shared` is a required layer in `unit-order`, no longer in parentheses, so renaming or deleting it breaks the contract (RED: 1 failed, 39 passed; GREEN: 40 passed). `make check` `768 passed, 5 deselected`, 13 contracts kept; `make test-docker` `1056 passed, 4 skipped, 5 deselected`, then `9 passed`.
   - Human checks: sign up and see the welcome email in the worker's log; trigger an unhandled error with alerts enabled and see the alert email.
6. **Per-module test commands** (O6), tested per Decision 7.
   - **Progress, 2026-11-13:** Step 6 done, in three TDD cycles, all in the `Makefile`, tested through `make -n` in `tests/base/unit/main/test_makefile_test_paths.py` (skipped in Docker, O8).
     - 6a: `unit=<name>` narrows the three test path lists to that unit's own folder (`tests/base/`, `tests/modules/<name>/` or `tests/shared/`). `make check unit=organizations` still runs every linter, `lint-imports` included, but only Organizations' light tests; `make test-docker unit=organizations` runs only its unit and infrastructure tests, and no migration tests. `unit=base` keeps the whole-app suites: characterisation, sanity, smoke and migrations (RED: 4 failed, 4 passed; GREEN: 8 passed). `make check` `772 passed, 5 deselected`.
     - 6b: an unknown name stops make before anything runs, listing the known units: `base`, `shared` and every folder under `tests/modules/`. Without it, a misspelt name narrows every list to nothing, and pytest given no paths falls back to `pyproject.toml`'s `testpaths`, so it would run every test, the infrastructure ones on the host included (RED: 1 failed, 8 passed; GREEN: 9 passed). `make check` `773 passed, 5 deselected`.
     - 6c: a known unit with no tests for a run stops `make test` and `make test-docker-app` the same way, naming the unit's folder. The check is per run, so a module with only infrastructure tests still runs them in Docker (RED: 2 failed, 10 passed; GREEN: 12 passed). `make check` `776 passed, 5 deselected`, 13 contracts kept; `make test-docker` `1056 passed, 12 skipped, 5 deselected`, then `9 passed` (the 12 skipped are the `make`-based tests, O8).
     - A unit's own run is for quick feedback only. The full `make check` and `make test-docker`, without `unit=`, still run before every commit, because a unit's own tests can't show what its change breaks elsewhere.
7. **The wiki generator, test-first.** `scripts/wiki/dependency_graph.py` learns `app.modules.<name>.<layer>` and `app.shared.<layer>` (RED: its tests, extended with module paths), and adds a unit-level graph.
   - **Progress, 2026-11-13:** Step 7 done, in three TDD cycles, in `scripts/wiki/dependency_graph.py`, tested in `tests/base/unit/main/wiki_tools/test_dependency_graph.py`.
     - 7a: `_layer_of()` reads the layer in every unit: at `app.base.<layer>` and `app.shared.<layer>`, and one name deeper at `app.modules.<name>.<layer>`. Every unit keeps the same four layers, so they share one layer graph (RED: 1 failed, 6 passed; GREEN: 7 passed). The real-graph test now also sees the modules' and `shared`'s imports, and still finds no forbidden layer edge. `make check` `777 passed, 5 deselected`.
     - 7b: `build_unit_edges()` reduces each import to the two units it joins. `base`'s `main/` is its own node, `base/main` (human maintainer's choice): it is the composition root, the one place that imports every unit, so drawn as part of `base` it would make `base` and each module seem to point at each other. Alembic's `env.py` reading the registry is left out through the `clean-architecture` contract's `ignore_imports`, as in the layer graph. The walk over the imports moved into one helper, `_edges_between`, shared by both graphs, and the layer graph's tests passed unchanged (RED: 1 error, an `ImportError`; GREEN: 8 passed). `make check` `778 passed, 5 deselected`.
     - 7c: `render_unit_mermaid()` draws the unit graph, and `make wiki-generate` writes it to a new page, `docs/wiki/generated/unit-graph.md`, for Step 8's unit-structure page to include. The nodes come from the edges, so a new module appears with no code change (RED: 1 error, an `ImportError`; GREEN: 9 passed). `make check` `779 passed, 5 deselected`, 13 contracts kept; `make test-docker` `1059 passed, 12 skipped, 5 deselected`, then `9 passed`.
     - `make wiki-generate` on the real code: the unit graph has eight arrows, `base/main` to `base`, `shared`, `organizations` and `notifications`; `notifications` to `organizations` and `base`; `organizations` and `shared` to `base`. No arrow points into `base/main`, `base` points at no unit, and only `base/main` points at `shared`. The layer graph's page is unchanged: the modules' imports add no layer pair `base` didn't already have.
8. **Docs and release bookkeeping.** The wiki pages that name moved paths (paths updated, prose kept per `agents.md` 3.3), a new page on the unit structure and how to add a module, the purpose and structure of the characterisation tests (`tests/characterisation/`) in the wiki's testing pages, explained with diagrams and few words (human maintainer, 2026-10-28), `CHANGELOG.md` and the version, the roadmap and README (their modular-monolith items still describe the earlier, all-contexts version), and `docs/plans/agents.md` 3.1 (under Option B the original author's files move under one prefix only).
   - **Progress, 2026-11-14:** Step 8 done.
     - The wiki: every line naming an old path updated, with nothing else changed (569 lines in 54 files, in 12 reviewed batches, inventory in `logs/step8-old-paths.log`; three more found by a wider search). `docs/wiki/content/testing/tdd.md` lines 35 and 84 keep the old paths, because they quote plan 4 word for word. Quoted code (the import-linter contracts, `WorkerProvider`'s docstring, `get_providers()`, the `Makefile`'s test paths) was re-quoted from today's code, and the sentences the move had made untrue were rewritten: email bound through `SharedEmailProvider`, the handlers in Notifications, routes and tables from the registry, the settings, the contract count and the test tiers.
     - Two new pages: `docs/wiki/content/architecture/units.md` (the units, what goes where and how to add a module, with the generated unit graph), which `index.md`, `layer-dependencies.md` and `core-layer.md` point to; and `docs/wiki/content/testing/characterisation-tests.md`, which `test-infrastructure.md` points to. `running-tests.md` gains a section on `unit=`.
     - `docs/plans/agents.md`: 3.1 says the original author's files are relocated under one prefix, `src/app/base/`; 1.3 names `unit=` as the human maintainer's quick-feedback tool; its paths are updated.
     - The README and the roadmap mark the modular monolith done (v0.20.0); the "group `core/commands/` and `core/queries/` by area" item is struck through as superseded, and a new item, Identity as a module, holds what remains (O9).
     - `CHANGELOG.md`: the 0.20.0 entry, including one line on outbox rows and queued messages (Decision 3) and one on logger names (O10).
     - Checks: no document names an old path apart from the two kept quotes; every relative link resolves; `make check` `779 passed, 5 deselected`, 13 contracts kept; `make wiki-build` builds, with warnings only for links into the source tree.
     - Afterwards, `app.modules` became a required layer in `unit-order`, as `app.shared` did in 5k: it is a package since Step 3 and both modules are registered, so renaming or deleting it now breaks the contract instead of passing quietly (RED: 1 failed, 40 passed; GREEN: 41 passed). `make check` `780 passed, 5 deselected`, 13 contracts kept.

## File summary

| Today | After |
|---|---|
| `src/app/{core,inbound,outbound,main}/` (everything not listed below) | `src/app/base/` + the same path below `src/app/` |
| The Organizations files listed under "What moves" | `src/app/modules/organizations/` + the same path below `src/app/` (the routes: `inbound/http/private_api/` and `inbound/http/public_api/`, Decision 10's amendment) |
| `src/app/core/common/events/handlers/` | `src/app/modules/notifications/core/common/events/handlers/` |
| `src/app/outbound/adapters/{console,smtp}_email_sender.py` (the port `src/app/core/common/ports/email_sender.py` goes to `base`) | `src/app/shared/outbound/adapters/` |
| `OrganizationSettings`, `EmailSettings` in `src/app/main/config/settings.py` | `src/app/modules/organizations/main/config/settings.py`, `src/app/shared/main/config/settings.py` |
| `tests/{characterisation,integration,performance,sanity,smoke,unit}/` | `tests/base/`, `tests/modules/<name>/` or `tests/shared/` + the same path below `tests/` |
| (new) | `src/app/base/main/modules.py`, `src/app/modules/*/main/module.py`, `src/app/modules/*/main/ioc/`, `src/app/modules/organizations/core/api.py`, `src/app/shared/main/module.py`, `src/app/shared/main/ioc/`, `tests/base/unit/architecture/`, the characterisation tests, the module test `conftest.py` files, the Makefile's `unit=` variable |
| The files listed under "What changes in place" | Their new paths, with the path and composition changes described there |

## Follow-ups and non-goals

- **Identity as a module** (users, account, sessions, API keys, the CLI's user commands), in its own plan, once this structure has proven itself. Decision 6 applies again then.
- **Option A** (the original layers back at the top of `src/app/`), only if the original author advises it.
- **Per-module migration histories,** if a module ever has to be removable together with its tables.
- **Tighten the public APIs** later (for example, Organizations' JOINs on `users_table` through a facade), each as its own change with its own tests, never during this plan.
- **Replacing dishka with plain-Python DI** stays its own roadmap item; units contribute plain dishka providers for now.
- **Search and file storage** (`docs/plans/11-search.md`, `docs/plans/12-file-storage.md`): their designs predate this plan; their paths are revised to "What goes where" before each starts.
- **A matching frontend:** the roadmap's "Frontend template" note describes the same module-per-bounded-context shape.
- **Not goals:** separate services, separate databases or schemas, runtime plugin loading, vertical slice architecture, renaming tables, changing the original author's code below the `base/` prefix (apart from `loader.py`'s `parents[5]`), or fixing any known issue along the way.

## Verification plan

- Every move step: the same `make check` and `make test-docker` counts before and after, all green, plus the Step 0 characterisation tests unchanged.
- Every new behaviour: RED with `uv run pytest <unit file> -v` or `make test-docker-file path=...`, GREEN with `make check`; `make test-docker` before every commit.
- Architecture: `lint-imports` with the contracts above, and `tests/base/unit/architecture/` proving each contract catches a fake violation and holds on the real code.
- Human checks, written into this plan as each step lands, in the `docs/plans/agents.md` 1.3 format (exact commands, seeded accounts, no placeholders). They will cover: both OpenAPI documents unchanged; the app, the CLI and the worker running from their new module paths; the worker delivering the welcome and invitation emails; the outbox rows naming the moved classes; the alert email; the per-unit test command on the real test tree; and the app with Notifications, then Organizations, deregistered. What the automated tests already prove is left out (`docs/plans/agents.md` 1.3).

## Human checks

One run, top to bottom, on one freshly seeded stack (rewritten 2026-11-14 under `docs/plans/agents.md` 1.3). They cover what only the running app shows: the worker importing the moved classes, the stored outbox rows, the CLI, the entrypoints with units removed and restored, and the per-unit test command on the real test tree. What the automated tests already prove is left out, apart from one public API read in check 5d. The stack is rebuilt only where a check changes code. They replace the per-step checks written as each step landed, which passed for Step 2 on 2026-11-03 and for Step 3 on 2026-11-06.

Every command's output is human-readable (JSON goes through `python3 -m json.tool`), and every command is explained right under it, flags included (`docs/plans/agents.md` 1.3).

### Setup

1. In your editor, make sure `.secrets` has these four values, and save. `.secrets` usually has some of these keys already, copied from `env.example` (for example `OPEN_DASHBOARDS=docs,public-docs,wiki` and `ALERT_ENABLED=false`): change the existing line's value rather than adding a second line, and add only the keys that are missing. The first turns the seed data on (it's `false` in `env.example`); the second stops `make upd` opening browser tabs; the last two turn alert emails on, for check 6:
   ```
   SEED_DB_WITH_TEST_DATA=true
   OPEN_DASHBOARDS=
   ALERT_ENABLED=true
   ALERT_TO_EMAILS=oncall@example.com
   ```
2. Leave these at their `env.example` values; don't override them in `.secrets`. The checks rely on them:
   - `ENVIRONMENT=development`: the Swagger pages are served (check 1).
   - `CELERY_ENABLED=true`: background handlers run in the `worker` container (checks 2 to 5).
   - `EMAIL_USE_CONSOLE=true`: emails are written to the log instead of sent.
   - `CELERY_OUTBOX_RETAIN_AFTER_RELAY=true`: outbox rows are kept after the worker relays them (checks 2, 3 and 5a).
3. Start from a fresh, freshly seeded database. Stop the stack; this discards the old database:
   ```shell
   make down
   ```
   **Breakdown:** stops every container in the dev stack and removes them, with the database volume.

   Then build and start it again, which migrates and seeds a new database:
   ```shell
   make upd
   ```
   **Breakdown:** writes the Compose environment from `.env` and `.secrets`, then runs `docker compose up -d --build` (rebuild the images from the current code, start every container, detached).

   If it ends with `dependency failed to start: container fast-api-clean-template-db_pg-1 is unhealthy`, Postgres took longer to set up the new database than its health check waits. Run it once more; the database is ready by then:
   ```shell
   make upd
   ```
   **Breakdown:** writes the Compose environment from `.env` and `.secrets`, then runs `docker compose up -d --build`.
4. Wait until the app answers. `make upd` returns as soon as the containers start, but the app first runs its migrations and seeds the database (hashing every seeded password), so it can take up to a minute to answer. This asks the app's readiness probe (`/healthz/`, which also queries the database) every 2 seconds, for up to a minute, and stops at the first answer:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' --retry 30 --retry-delay 2 --retry-all-errors http://localhost:8000/healthz/ | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors (for example `Failed to connect to localhost port 8000`, which a bare `000` doesn't explain); `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr, so it stays out of the JSON; `--retry 30 --retry-delay 2` tries up to 30 more times, 2 seconds apart; `--retry-all-errors` retries on any error, including a refused connection; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, then `"OK"`. If curl gives up instead (an error such as `Failed to connect to localhost port 8000`, then `000`), the app didn't start. Read the end of its log for the reason:
   ```shell
   docker compose -p fast-api-clean-template logs app --tail 50
   ```
   **Breakdown:** `-p fast-api-clean-template` names the project `make upd` started (`APP_SERVICE_NAME`; without it, Compose looks for a project named after the folder, which isn't running); `logs app` prints the app container's log; `--tail 50` keeps only the last 50 lines.
5. Each user gets their own cookie file in `/tmp` (for example `/tmp/peter-parker.cookies`). Every check logs in each user it acts as, because a session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN`); an expired cookie gets `401`. Run every command in the same terminal, top to bottom, from the repository root.

### Seeded data used (from `scripts/seed_db.py`)

- `peter-parker` (`SpideySense2024!`): platform USER. He owns the Daily Bugle (`a0000000-0000-4000-8000-000000000004`) and is an accepted member of the Avengers, the X-Men and the Defenders: 4 organizations in all. His API key `ak_seed-peter-parker-valid` is valid.
- `miles-morales` (`WebSlingerHero1!`): platform ADMIN, who may create users through the CLI.
- Not seeded, and created by the checks: `kitty-pryde` (check 2), `kurt-wagner` (check 4), `logan-howlett` and `scott-summers` (check 5).

### The checks

1. **Swagger: both apps serve their pages.**

   **Why:** the characterisation tests pin both OpenAPI documents to committed snapshots (Step 0). This shows the pages themselves are served by the moved apps, as a developer would open them.

   **Acts on:** the web app's and the public API's Swagger pages.

   Open the web app's page in the browser:
   ```
   http://localhost:8000/docs
   ```
   Then the public API's:
   ```
   http://localhost:8000/public/docs
   ```
   Expect each page to load and list its route groups: the web app's include Account, Users and Organizations; the public API's include API Keys, Account and Organizations.

2. **Sign-up: the worker sends the welcome email, and the outbox row names the moved classes (200).**

   **Why:** signing up raises `UserRegisteredEvent` (still in `base`), whose handler `SendWelcomeEmail` now lives in the Notifications module. The app writes an outbox row naming both classes by their dotted import paths; the separate `worker` container relays it to Celery, imports both classes by those names, and sends the email through `shared`'s `EmailSender`. The integration tests run Celery in-process, so only here does the real worker import the moved classes. The stored row is the one place the move shows up in data, so it's read straight from the database, as raw SQL.

   **Acts on:** a new account, `kitty-pryde`.

   Sign up `kitty-pryde`, with no cookie:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "kitty-pryde", "password": "PhaseShift2024!", "email": "kitty.pryde@xmen.org", "phone_number": "0821000016"}' \
     | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr, so it stays out of the JSON; `-X POST` sends a POST; `-H 'Content-Type: application/json'` says the body is JSON; `-d '…'` is the body; `\` at a line's end continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, with kitty's whole user: `"username": "kitty-pryde"`, `"email": "kitty.pryde@xmen.org"`, `"phone_number": "27821000016"`, `"role": "user"`. Wait about 5 seconds (the worker checks the outbox every 3 seconds, `CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS`), then read the worker's log:
   ```shell
   docker compose -p fast-api-clean-template logs worker | grep 'kitty.pryde'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the project `make upd` started (without it, Compose looks for a project named after the folder, which isn't running); `logs worker` prints the worker container's log; `| grep 'kitty.pryde'` keeps only the lines containing that text.

   Expect four lines, in this order (`grep`'s `.` matches any character, so the HTML line with `kitty-pryde` shows too):
   - `Sending welcome email to kitty.pryde@xmen.org`
   - `EMAIL [to=['kitty.pryde@xmen.org']] [cc=()] [bcc=()] [subject=Welcome to the platform!]`
   - `<h1 style="color: #2c3e50;">Welcome, kitty-pryde!</h1>`
   - `Welcome email sent to kitty.pryde@xmen.org`

   Then read the sign-up's outbox rows, every column. Seeding raises no events, so on a fresh database this sign-up wrote the only one:
   ```shell
   docker compose -p fast-api-clean-template exec db_pg psql -U postgres -d clean-example -x -c "SELECT * FROM event_outbox WHERE event_type LIKE '%:UserRegisteredEvent';"
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `exec db_pg` runs a command inside the Postgres container; `psql -U postgres -d clean-example` connects as the `postgres` user to the app's database; `-x` prints each column on its own line; `-c "…"` runs one SQL statement; `SELECT *` returns every column; `LIKE '%:UserRegisteredEvent'` keeps rows whose `event_type` ends with that class name (`%` matches anything).

   Expect exactly one record: `event_type` `app.base.core.common.events.user_registered:UserRegisteredEvent`, `handler_type` `app.modules.notifications.core.common.events.handlers.send_welcome_email:SendWelcomeEmail` (a colon separates the module from the class), a `payload` holding kitty's username and email, and a `processed_at` that isn't empty (the worker relayed it).

3. **Invitation: Notifications' second handler, through Organizations' public API (201).**

   **Why:** inviting someone raises `OrganizationInvitationCreatedEvent`, which now lives in the Organizations module. Notifications reaches it only through Organizations' public API, `core/api.py`, which the `organizations-internals` contract enforces. The email in the worker's log proves the subscription works through that import; the outbox row shows the event's module path.

   **Acts on:** the Daily Bugle (`a0000000-0000-4000-8000-000000000004`), owned by `peter-parker`; the invitee is `kitty-pryde` from check 2.

   Log in as `peter-parker`:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr, so it stays out of the JSON; `-c /tmp/peter-parker.cookies` saves the session cookie the app sets into that file; `-X POST` sends a POST; `-H 'Content-Type: application/json'` says the body is JSON; `-d '…'` is the body, peter's username and password; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, with `"username": "peter-parker"`. Then, as `peter-parker`, invite `kitty-pryde` to the Daily Bugle as a member:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000004/members/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "kitty-pryde", "role": "member"}' | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `-b /tmp/peter-parker.cookies` sends the session cookie saved at login, so the app knows it's peter; `-X POST` sends a POST to the Daily Bugle's members; `-H 'Content-Type: application/json'` says the body is JSON; `-d '…'` is the body, the invitee and the role; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `201`, with a `membership_id` and an `expires_at` 7 days from now (`ORGANIZATION_INVITATION_TTL_DAYS`). Wait about 5 seconds, then read the worker's log:
   ```shell
   docker compose -p fast-api-clean-template logs worker | grep -E 'invitation email|invited to join'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs worker` prints the worker container's log; `| grep -E '…|…'` keeps the lines matching either phrase (`-E` allows the `|` meaning "or").

   Expect four lines, in this order:
   - `Sending organization invitation email to kitty.pryde@xmen.org`
   - `EMAIL [to=['kitty.pryde@xmen.org']] [cc=()] [bcc=()] [subject=You're invited to join Daily Bugle]`
   - `<h1 style="color: #2c3e50;">You're invited to join Daily Bugle</h1>`
   - `Organization invitation email sent to kitty.pryde@xmen.org`

   Then read the invitation's outbox rows, every column:
   ```shell
   docker compose -p fast-api-clean-template exec db_pg psql -U postgres -d clean-example -x -c "SELECT * FROM event_outbox WHERE event_type LIKE '%:OrganizationInvitationCreatedEvent';"
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `exec db_pg` runs a command inside the Postgres container; `psql -U postgres -d clean-example` connects as the `postgres` user to the app's database; `-x` prints each column on its own line; `-c "…"` runs one SQL statement; `SELECT *` returns every column; `LIKE '%:OrganizationInvitationCreatedEvent'` keeps rows whose `event_type` ends with that class name (`%` matches anything).

   Expect exactly one record: `event_type` `app.modules.organizations.core.common.events.organization_invitation_created:OrganizationInvitationCreatedEvent`, `handler_type` `app.modules.notifications.core.common.events.handlers.send_organization_invitation_email:SendOrganizationInvitationEmail`, a `payload` holding `"organization_name": "Daily Bugle"`, kitty's email and the same `membership_id`, and a `processed_at` that isn't empty.

4. **The CLI: creating a user sends the welcome email.**

   **Why:** `make cli` runs `python -m app.base.main.cli` inside the app container, and the CLI builds its own container, whose handler registry comes from the registered units (`CliProvider(units)`), with Notifications' CLI provider binding the welcome email's handler. An email in the worker's log proves the CLI subscribed it and staged the outbox row.

   **Acts on:** a new account, `kurt-wagner`, created by `miles-morales`.

   Run:
   ```shell
   make cli args="users create-user --username kurt-wagner --email kurt.wagner@xmen.org --phone-number 0821000017"
   ```
   **Breakdown:** `make cli` runs the CLI inside the app container (`python -m app.base.main.cli`); `args="…"` passes it the command and its options: `users create-user`, with the new user's `--username`, `--email` and `--phone-number`.

   It asks three things, in this order. First a username (who you are). Answer:
   ```
   miles-morales
   ```
   Then his password (nothing is shown as you type it). Answer:
   ```
   WebSlingerHero1!
   ```
   Then the new user's password, asked by `create-user` (nothing is shown either). Answer:
   ```
   Nightcrawler#2024
   ```
   Expect JSON with the new user's `id` and `created_at`. Wait about 5 seconds, then read the worker's log:
   ```shell
   docker compose -p fast-api-clean-template logs worker | grep 'kurt.wagner'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs worker` prints the worker container's log; `| grep 'kurt.wagner'` keeps only the lines containing that text.

   Expect four lines, in this order:
   - `Sending welcome email to kurt.wagner@xmen.org`
   - `EMAIL [to=['kurt.wagner@xmen.org']] [cc=()] [bcc=()] [subject=Welcome to the platform!]`
   - `<h1 style="color: #2c3e50;">Welcome, kurt-wagner!</h1>`
   - `Welcome email sent to kurt.wagner@xmen.org`

5. **The registry: modules removed and restored on the running app.**

   **Why:** user story 4. Notifications can be removed by deleting its one registry entry; Organizations can't be removed alone, because Notifications needs it, and every entrypoint must say so at start-up rather than fail later; with both removed the app still runs, and putting them back restores everything, with the data kept. The unit and integration tests prove each piece separately (`test_modules.py`, `test_app_without_notifications.py`); only the running app shows the app, the worker and the seed script (which has no tests, `docs/plans/agents.md` 2.1) reading the same registry. Four registrations, each one edit to line 232 of `src/app/base/main/modules.py` and one restart; the database is kept throughout.

   **Acts on:** the registry line; new accounts `logan-howlett` (signed up without Notifications) and `scott-summers` (after it's back); `peter-parker`'s login and API key.

   **5a. Notifications removed: sign-up still works, and sends no email.** This is an edit in your editor, not a terminal command. Open `src/app/base/main/modules.py`, change line 232 from `UNITS: tuple[Unit, ...] = (shared, organizations, notifications)` to the line below, and save. Leave the imports above it as they are, so each change stays one line:
   ```python
   UNITS: tuple[Unit, ...] = (shared, organizations)
   ```
   Confirm the edit:
   ```shell
   grep -n '^UNITS' src/app/base/main/modules.py
   ```
   **Breakdown:** `-n` prints the line number; `'^UNITS'` matches lines starting with `UNITS` (`^` is the start of a line).

   Expect `232:UNITS: tuple[Unit, ...] = (shared, organizations)`. Then rebuild and restart the app and the worker with the change:
   ```shell
   make upd
   ```
   **Breakdown:** writes the Compose environment from `.env` and `.secrets`, then runs `docker compose up -d --build`, which rebuilds the images with the edited registry and recreates the containers; the database volume is kept.

   Wait until the app answers again. The restart runs the migrations and the seeding first (seeding skips what already exists):
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' --retry 30 --retry-delay 2 --retry-all-errors http://localhost:8000/healthz/ | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `--retry 30 --retry-delay 2 --retry-all-errors` tries up to 30 more times, 2 seconds apart, on any error; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, then `"OK"`: the app started without Notifications. Then sign up `logan-howlett`, with no cookie:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "logan-howlett", "password": "Adamantium2024!", "email": "logan.howlett@xmen.org", "phone_number": "0821000018"}' \
     | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `-X POST` sends a POST; `-H 'Content-Type: application/json'` says the body is JSON; `-d '…'` is the body; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, with logan's whole user, `"username": "logan-howlett"`. Wait about 5 seconds, then read the worker's log:
   ```shell
   docker compose -p fast-api-clean-template logs worker | grep 'logan.howlett'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs worker` prints the worker container's log; `| grep 'logan.howlett'` keeps only the lines containing that text.

   Expect no output: no welcome email. Then look for an outbox row about logan, every column:
   ```shell
   docker compose -p fast-api-clean-template exec db_pg psql -U postgres -d clean-example -x -c "SELECT * FROM event_outbox WHERE payload::text LIKE '%logan-howlett%';"
   ```
   **Breakdown:** `exec db_pg` runs a command inside the Postgres container; `psql -U postgres -d clean-example` connects as the `postgres` user to the app's database; `-x` prints each column on its own line; `-c "…"` runs one SQL statement; `payload::text` turns the stored payload into text, so the `LIKE` match works whatever the column's type; `'%logan-howlett%'` matches the name anywhere in it (`%` matches anything).

   Expect `(0 rows)`: with nothing subscribed to `UserRegisteredEvent`, nothing was staged.

   **5b. Organizations removed alone: refused.** Change the same line to the line below, and save:
   ```python
   UNITS: tuple[Unit, ...] = (shared, notifications)
   ```
   Confirm the edit:
   ```shell
   grep -n '^UNITS' src/app/base/main/modules.py
   ```
   **Breakdown:** `-n` prints the line number; `'^UNITS'` matches lines starting with `UNITS`.

   Expect `232:UNITS: tuple[Unit, ...] = (shared, notifications)`. Then rebuild and restart:
   ```shell
   make upd
   ```
   **Breakdown:** writes the Compose environment from `.env` and `.secrets`, then runs `docker compose up -d --build`, which rebuilds the images with the edited registry and recreates the containers; the database volume is kept.

   Wait about 15 seconds (the app container runs the migrations, then the seed script, which builds the app and stops), then search the app's log for the refusal. If it prints nothing, wait a few seconds more and run it again:
   ```shell
   docker compose -p fast-api-clean-template logs app | grep 'MissingUnitError'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs app` prints the app container's log; `| grep 'MissingUnitError'` keeps only the lines naming that error.

   Expect a line ending `MissingUnitError: Unit 'notifications' needs unit 'organizations', which is not registered.`

   **5c. Both removed: the app runs without Organizations.** Change the same line to the line below, and save:
   ```python
   UNITS: tuple[Unit, ...] = (shared,)
   ```
   Confirm the edit:
   ```shell
   grep -n '^UNITS' src/app/base/main/modules.py
   ```
   **Breakdown:** `-n` prints the line number; `'^UNITS'` matches lines starting with `UNITS`.

   Expect `232:UNITS: tuple[Unit, ...] = (shared,)`. Then rebuild and restart:
   ```shell
   make upd
   ```
   **Breakdown:** writes the Compose environment from `.env` and `.secrets`, then runs `docker compose up -d --build`, which rebuilds the images with the edited registry and recreates the containers; the database volume is kept.

   Wait until the app answers:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' --retry 30 --retry-delay 2 --retry-all-errors http://localhost:8000/healthz/ | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `--retry 30 --retry-delay 2 --retry-all-errors` tries up to 30 more times, 2 seconds apart, on any error; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, then `"OK"`: the app started without Organizations. `make upd` recreated the container, so its log holds only this start; search it for the organization seeding's lines:
   ```shell
   docker compose -p fast-api-clean-template logs app | grep 'Seed organization'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs app` prints the app container's log; `| grep 'Seed organization'` keeps only the lines the organization seeding writes when it finds an organization already there.

   Expect no output: the seed script ran no organization seeds. Log in as `peter-parker`:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}' | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `-c /tmp/peter-parker.cookies` saves the session cookie into that file; `-X POST` sends a POST; `-H 'Content-Type: application/json'` says the body is JSON; `-d '…'` is peter's username and password; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`: users still work. Then, as `peter-parker`, ask for his organizations:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/organizations/?limit=50' | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `-b /tmp/peter-parker.cookies` sends his saved session cookie; with no `-X`, `curl` sends a GET; the URL is in quotes so the shell doesn't treat `?` as a filename wildcard; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `404`, with `"detail": "Not Found"`: the route isn't served. Then the same through the public API, with his key:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' http://localhost:8000/public/v1/organizations/ \
     -H 'X-API-Key: ak_seed-peter-parker-valid' | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; with no `-X`, `curl` sends a GET; `-H 'X-API-Key: …'` sends peter's seeded API key, which is how the public API knows who's calling; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `404`, with `"detail": "Not Found"`.

   **5d. Both back: the routes return, nothing was lost, and the email is back.** Change the same line back to the line below, and save:
   ```python
   UNITS: tuple[Unit, ...] = (shared, organizations, notifications)
   ```
   Confirm the edit:
   ```shell
   grep -n '^UNITS' src/app/base/main/modules.py
   ```
   **Breakdown:** `-n` prints the line number; `'^UNITS'` matches lines starting with `UNITS`.

   Expect `232:UNITS: tuple[Unit, ...] = (shared, organizations, notifications)`. If it's left out, `make check` fails at `test_the_registry_lists_every_unit_in_registration_order`. Then rebuild and restart:
   ```shell
   make upd
   ```
   **Breakdown:** writes the Compose environment from `.env` and `.secrets`, then runs `docker compose up -d --build`, which rebuilds the images with the restored registry and recreates the containers; the database volume is kept.

   Wait until the app answers:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' --retry 30 --retry-delay 2 --retry-all-errors http://localhost:8000/healthz/ | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `--retry 30 --retry-delay 2 --retry-all-errors` tries up to 30 more times, 2 seconds apart, on any error; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, then `"OK"`. The organization seeding ran again and found its data already there:
   ```shell
   docker compose -p fast-api-clean-template logs app | grep 'Seed organization'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs app` prints the app container's log; `| grep 'Seed organization'` keeps only the lines the organization seeding writes when it finds an organization already there.

   Expect four lines, one per seeded organization, each ending `already exists, skipping.` Then the same public API request as in 5c, with peter's key; only the registry has changed. This is the one check that repeats an integration test (`test_organization_reads.py`), kept because it shows the second app's container rebuilt from the registry, side by side with 5c's 404:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' http://localhost:8000/public/v1/organizations/ \
     -H 'X-API-Key: ak_seed-peter-parker-valid' | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; with no `-X`, `curl` sends a GET; `-H 'X-API-Key: …'` sends peter's seeded API key, which is how the public API knows who's calling; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, with `"total": 4`: his four organizations, the Daily Bugle with `"role": "owner"`. Then sign up `scott-summers`, with no cookie:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' -X POST http://localhost:8000/api/v1/account/signup/ \
     -H 'Content-Type: application/json' \
     -d '{"username": "scott-summers", "password": "OpticBlast2024!", "email": "scott.summers@xmen.org", "phone_number": "0821000019"}' \
     | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; `-X POST` sends a POST; `-H 'Content-Type: application/json'` says the body is JSON; `-d '…'` is the body; `\` continues the command on the next line; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `200`, with `"username": "scott-summers"`. Wait about 5 seconds, then read the worker's log:
   ```shell
   docker compose -p fast-api-clean-template logs worker | grep 'scott.summers'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs worker` prints the worker container's log; `| grep 'scott.summers'` keeps only the lines containing that text.

   Expect four lines, in this order: the welcome email is back.
   - `Sending welcome email to scott.summers@xmen.org`
   - `EMAIL [to=['scott.summers@xmen.org']] [cc=()] [bcc=()] [subject=Welcome to the platform!]`
   - `<h1 style="color: #2c3e50;">Welcome, scott-summers!</h1>`
   - `Welcome email sent to scott.summers@xmen.org`

6. **The alert email: the web app sends it through `shared` (500).**

   **Why:** `base`'s error alerting (`src/app/base/inbound/http/errors/exception_middleware.py`) asks the web app's container for `EmailSender`, which `shared` now binds. `/debug/test-error/` raises an error that nothing handles, on purpose. Setup step 1 turned alerts on, and 5d's restart started a fresh app container, which also cleared the alert cooldown (`ALERT_COOLDOWN_S`: one alert per exception type per 300 seconds, kept in the app's memory). It's a `GET` that stores nothing, so there's nothing to read back.

   **Acts on:** the debug route, called with no cookie (an anonymous caller).

   Call it:
   ```shell
   curl -sS -w '%{stderr}%{http_code}\n' http://localhost:8000/debug/test-error/ | python3 -m json.tool
   ```
   **Breakdown:** `-sS` keeps `curl` quiet but still prints its own errors; `-w '%{stderr}%{http_code}\n'` prints the status code first, on its own line, to stderr; with no `-X`, `curl` sends a GET; no cookie is sent, so the caller is anonymous; `| python3 -m json.tool` pretty-prints the JSON.

   Expect `500`, then `"code": "HTTP_500_INTERNAL_SERVER_ERROR"` and `"message": "Internal server error"`. Then read the app's log. It holds only 5d's start, and the worker sends the welcome emails, so the only email the app itself wrote is the alert:
   ```shell
   docker compose -p fast-api-clean-template logs app | grep -E 'EMAIL \[to=|Unhandled server error'
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `logs app` prints the app container's log; `| grep -E '…|…'` keeps the lines matching either pattern (`-E` allows the `|` meaning "or"); `\[` matches a literal `[`.

   Expect one JSON log line from the logger `app.shared.outbound.adapters.console_email_sender` (each log record is one line, so the email's header and its HTML body arrive together, joined by `\n`). Its `message` holds:
   - the header `EMAIL [to=['oncall@example.com']] [cc=[]] [bcc=[]] [subject=[ALERT] ValueError on GET /debug/test-error/]`;
   - the HTML body, starting `<h2>Unhandled server error</h2>`, naming the type `ValueError`, the message `Test error for alerting - this triggers a 500 and email alert`, the request `GET /debug/test-error/` and the user `anonymous (no valid session)`.

   If it prints nothing, check that the running app has alerts on (Setup step 1). This prints `true`, then `oncall@example.com`:
   ```shell
   docker compose -p fast-api-clean-template exec app printenv ALERT_ENABLED ALERT_TO_EMAILS
   ```
   **Breakdown:** `-p fast-api-clean-template` names the running project; `exec app` runs a command inside the app container; `printenv NAME…` prints each named environment variable that is set.

7. **One unit's tests: `unit=` on the real test tree.**

   **Why:** the `make -n` tests only see a fake test tree; these run the real commands on the real one. None of them need the dev stack or the seed data. Each run's output is saved to `logs/`, so the search after it can read it.

   **7a. A misspelt unit is refused before anything runs.** A name make doesn't know would narrow every list to nothing, and pytest given no paths runs every test (`pyproject.toml`'s `testpaths`), so make stops first, naming the units it knows:
   ```shell
   make check unit=organisations
   ```
   **Breakdown:** `make check` runs the linters and the light tests; `unit=organisations` asks for one unit's tests, misspelt on purpose (British "s").

   Expect a single line ending `Unknown unit 'organisations'. Known units: base notifications organizations shared.  Stop.`, and no linter or pytest output: nothing ran.

   **7b. `make check unit=organizations`: every linter, and only Organizations' light tests.** The import rules are about the whole graph, so the linters still run over everything; only the test list is narrowed. Like `make check`, it may reformat files, and it rewrites `htmlcov/` with this run's coverage only (the next full `make check` restores it):
   ```shell
   make check unit=organizations 2>&1 | tee logs/check-unit-organizations.log
   ```
   **Breakdown:** `make check` runs the linters and the light tests; `unit=organizations` narrows the tests to `tests/modules/organizations/`; `2>&1` sends error output into the same stream as normal output; `| tee logs/check-unit-organizations.log` shows the output and saves a copy to that file.

   Expect the linters clean, `13 kept, 0 broken.` from `lint-imports`, then `159 passed`. Then count the tests that ran from anywhere else:
   ```shell
   grep -E '^tests/.*::' logs/check-unit-organizations.log | grep -vc '^tests/modules/organizations/'
   ```
   **Breakdown:** `grep -E '^tests/.*::'` keeps the lines naming a test (they start with `tests/` and contain `::`); `| grep -vc '…'` counts (`-c`) the lines that don't (`-v`) start with Organizations' test folder.

   Expect `0`.

   **7c. Optional, on request: `make test-docker unit=organizations`.** It repeats 7b's narrowing in the throwaway Docker test stack, including the infrastructure tests and skipping the migration tests, and takes a few minutes, so it runs only when the human maintainer asks for it. It rewrites `htmlcov-docker/` with this run's coverage only:
   ```shell
   make test-docker unit=organizations 2>&1 | tee logs/test-docker-unit-organizations.log
   ```
   **Breakdown:** `make test-docker` starts a throwaway Docker test stack, runs the tests in it, then removes it; `unit=organizations` narrows the tests to `tests/modules/organizations/`; `2>&1` sends error output into the same stream as normal output; `| tee logs/test-docker-unit-organizations.log` shows the output and saves a copy to that file.

   Expect `249 passed` (159 unit and 90 infrastructure tests), then `PYTEST_PATHS_MIGRATIONS or MIGRATION_DB_SERVICE is empty, skipping migrations tests`. Then count the tests that ran from anywhere else:
   ```shell
   grep -E '^tests/.*::' logs/test-docker-unit-organizations.log | grep -vc '^tests/modules/organizations/'
   ```
   **Breakdown:** `grep -E '^tests/.*::'` keeps the lines naming a test (they start with `tests/` and contain `::`); `| grep -vc '…'` counts (`-c`) the lines that don't (`-v`) start with Organizations' test folder.

   Expect `0`.

### After the checks

In your editor, set `ALERT_ENABLED` back to `false` in `.secrets`, and save. The next `make upd` starts with alerts off again.