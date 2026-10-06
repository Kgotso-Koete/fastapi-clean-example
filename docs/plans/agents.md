# Working agreement: the human maintainer and AI coding agents

## Purpose of this codebase

Every rule in this document exists because of what this codebase is for, so read this first.

- **It is a public, open-source reference template** for building backend services in FastAPI with Domain-Driven Design (DDD), Clean Architecture, CQRS and Test-Driven Development (TDD). It extends the upstream `fastapi-clean-example` template (https://github.com/ivan-borovets/fastapi-clean-example) with production-grade capabilities, one bounded context and one building block at a time, tracked in `docs/plans/0-production-readiness-roadmap.md`. Examples include domain events and an outbox, observability, a CLI, a public API with API keys, and organizations.
- **It is built to help maintainers of commercial and hobby projects small enough to be built and maintained by a solo developer.** It helps them solve the complexity, maintainability, testability and other technical debt problems such projects run into as they grow: a codebase one person can still understand, change safely and keep healthy years later. Real products, commercial or hobby, are built on it through private forks. So it has to stay generic, and small enough for one developer to run, understand and afford: the smallest viable infrastructure by default, with heavier infrastructure as an optional upgrade.
- **It builds comprehensive, production-ready vertical slices that many applications can build on and depend on.** A vertical slice is a capability built all the way through the stack, from domain and use cases to persistence, HTTP and tests, finished to production quality rather than sketched. The slices this codebase provides are the ones nearly every application needs:
  - user-scoped use cases: accounts, authentication, profiles, API keys
  - organization-scoped use cases: organizations, memberships, invitations, roles
  - notification use cases: domain events, email and similar delivery

  Any other vertical slice, and any business-specific logic, belongs in the products built on top, not here. It is added only when the human maintainer explicitly asks for it, or has specified it in a plan in `docs/plans/` (see 4.5).
- **It exists to solve small-scale architectural, complexity and maintainability problems properly.** The value of this codebase is its discipline: clear layering, explicit design decisions, and every behavior pinned by a test. A shortcut that makes something work while eroding that discipline defeats the purpose of the codebase, even when the feature appears to work.
- **It is also how the human maintainer learns and masters a complex system.** The human maintainer extends it with an AI agent as a pair programmer. When a person is learning a system, changing pieces whose consequences they don't fully understand is exactly how subtle, hard-to-predict breakage gets in. Adding self-contained, well-explained, well-tested pieces lets them reason about each addition on its own.

That purpose is why the rules below look the way they do:
- **strict TDD and never bypassing checks:** the discipline is the product.
- **additive building blocks, small diffs, and extra care with the original author's code:** don't break trusted code, and let a learner reason about additions in isolation.
- **the smallest viable infrastructure:** a template one developer can run, understand and afford.
- **explaining code before showing it, and commenting liberally:** learning.
- **plans in the repository, and this document as the source of truth:** AI agents forget between sessions; the repository doesn't.
- **keeping examples generic and never leaking a private fork:** a public template.
- **complete, production-ready slices, and no business-specific logic:** a foundation many different applications can depend on.

## About this document

This document lists the standing rules for how the human maintainer of this repository and an AI coding agent work together on it. Each rule was set, or corrected, by the human maintainer during real pair-programming sessions. Each one records the rule, the reason for it, and how to apply it, so a new session, or a new agent, can follow it without having to relearn it the hard way.

These rules apply to all work in this codebase, not to one feature. When a rule and an AI agent's own default habits disagree, the rule wins.

**This document is the only source of truth for the rules an AI agent follows in this codebase.** An AI agent may also keep its own notes about these rules in whatever persistence its tool offers (saved memories, custom instructions, rules files, project settings), but those notes must always stay in sync with this document:
- Whenever the human maintainer sets or corrects a rule, the AI agent updates this document in the same change as its own notes.
- If the two ever disagree, this document wins, and the AI agent fixes its notes to match.
- A rule that exists only in an AI agent's private notes, and not here, is not a rule of this codebase.

## Who is who

This document refers to three distinct parties. They are never interchangeable.

- **The human maintainer** is the person who owns this repository and is in charge of it. They decide its composition (what gets built, and in what order), orchestrate the work (which step comes next, when a RED or GREEN is confirmed, when something is committed and merged), and make the architecture and design calls. They are accountable for everything that lands in the codebase. They run every command, approve every change, and are the only party who can grant an exception to any rule below.
- **The AI agent** is whichever AI coding assistant is pair-programming with the human maintainer in a given session, whatever the tool, model or vendor. Every rule here applies to any AI agent equally. It proposes designs, writes tests and code within these rules, explains what it writes, and hands commands to the human maintainer to run. It never decides on its own to relax a rule, and it keeps no memory between sessions except what's written down (this document, the plans in `docs/plans/`, and its own saved notes).
- **The original author** is the author of the upstream `fastapi-clean-example` template this repository was built from (https://github.com/ivan-borovets/fastapi-clean-example). They are not a participant in these sessions. "The original author's code" means the state of the code before the human maintainer and the AI agent began extending it together. Section 3 explains why that code is handled with extra care.

---

## 1. Commands and execution

### 1.1 The human maintainer runs every command

The human maintainer runs every terminal command (shell, git, docker, make, uv, pytest, and so on) unless they explicitly say otherwise for a specific command. The AI agent does not run commands itself. It hands over the exact command to run, with a short explanation of what that command does, so the human maintainer understands it before running it.

- This holds whatever permission or autonomy setting the AI agent's tool is running under. An auto-approving mode, or earlier commands in the same session that ran without objection, is never authorization to keep running commands. Such settings change how much the AI agent can decide without asking; they do not change who runs commands.
- Read-only commands (`ls`, `grep`, `cat`, `find`) are not exempt. To inspect the codebase, the AI agent uses its tool's built-in file-reading and search features, not shell commands.
- **When the human maintainer does authorize a specific command** ("run the command", "just do it"), the AI agent runs it immediately, in that same turn, with no re-explaining, hedging or second confirmation.
- **Standing exception: fetching past conversation text.** When the human maintainer asks for messages from a previous session, or the exact text of an earlier message, the AI agent retrieves it itself straight away (see section 8).

### 1.2 Use the real entrypoint for verification

When giving manual verification steps, use the real top-level command a user or a deployment would run (a Makefile target, a documented script), not a hand-built sequence of its internal sub-steps. Example: `make down` then `make upd`, not `make docker-env` followed by `make upd`, because `upd` already depends on `docker-env`. Verification should exercise the whole real workflow, not an approximation that happens to reach the same state.

### 1.3 The verification ladder

- **RED step:** run the single test file, `uv run pytest <path> -v`, or `make test-docker` when the test needs real infrastructure. A RED has to be seen as a running test failure. `make check` stops at lint and mypy before any test runs, so it can't show a RED.
- **GREEN step:** run `make check`, not just `uv run pytest tests/unit`. `make check` covers everything the narrower command does and more (ruff format and lint, the import-linter layer and CQRS contracts, mypy, then the light test paths). It catches a GREEN whose tests pass but that breaks a type, a layer contract or formatting.
- **Anything touching infrastructure (Postgres, Redis, Celery, the worker):** run `make check`, then `make test-docker`, and only then do manual checks (`make upd` and inspection). Don't skip the automated integration tier.
- **The final and ultimate check: simple, human-driven, common-sense verification.** Automated tests prove what they were written to prove. The last rung is a small list of manual checks the human maintainer can do and see for themselves, without complex container workflows or reading test output:
  - a request from Postman or the browser
  - an AI-assisted `curl` command
  - looking at the response or the page
  - confirming it matches what a user would expect

  Every feature's verification plan ends with such a list. Keep it short (a handful of checks) and concrete: the exact request, and what a correct result looks like, so anyone can sense-check it in a few minutes.
- **Seed data comes before the human check, not after it.** Most human checks run against data the seed script (`scripts/seed_db.py`) has already created: named accounts, organizations, roles and every interesting state (pending, expired, accepted, and so on). The human maintainer creates only a little data by hand, to exercise the create/update/delete paths themselves. So whenever a slice becomes reachable by a human (its routes exist), the seed data for it is added in that same step, before the human check is handed over. It is never deferred to the end of the plan. An AI-assisted human check that makes the human build all the test data from scratch has missed the point.
- **Human checks are written down in the feature's plan, as copy-pasteable `curl` commands.** Each check is a numbered item in a "Human checks" section of that feature's plan in `docs/plans/`. It gives the exact, human-readable `curl` command (with a login step and one cookie file per user where needed), which seeded account it acts as, and the expected status and message. The checks live in the plan, not only in chat, so they survive between sessions and can be re-run at any time. Aim for 5 to 20 checks per step. Seeded rows the checks act on get fixed ids, so the commands can be pasted as written.
- **Human checks are exact and unambiguous: no placeholders, ever.** The human maintainer's words: "No placeholder values please, it makes life hard for no reason. No ambiguity."
  - Every login is written out as its own command, with the real username and password, right before that user's first request. Never "log in as X first" without the command.
  - No `<id>`, `<username>` or similar to fill in. A value only known at run time (such as a new row's id) is captured into a shell variable by the command that creates it, then reused as `$VARIABLE`.
  - No "re-run check N" or "run it again": repeat the command in full where it's needed, so the checks read top to bottom in the order they're run.
- **Every human check explains what it's testing and why.** A short title like "A MEMBER can't invite" isn't enough. Each check gets a **Why** line: the rule being tested (for example "inviting needs at least ADMIN"), why the rule exists, and why this status code rather than a similar one (for example 403 rather than 404). A feature with roles or permissions also gets a short "who can do what" reference before its checks. The human maintainer's words: "The more I know what I am testing against, the easier."
- **Prove every assumption with a command before relying on it.** If a check depends on a starting state ("peter is a MEMBER of the Avengers", "diana's invitation has expired", "this id is matt's invitation"), it first runs a read-only command that shows that state, before the command under test. The same goes for the result: a check that changes something ends with a command that shows the change, rather than trusting the status code. The human maintainer's words: "These type of assumptions should have a CURL to demonstrate that he is a member before we can show that he can't invite anyone because he is not an ADMIN." Pipe JSON through a pretty-printer (`python3 -m json.tool`) so it's easy to read.
  - Each check proves its *own* starting state, right before its command under test, even if an earlier check already showed it. Never write "check N proved…": the human maintainer shouldn't have to remember what an earlier check printed.
  - Each check logs in every user it acts as, at its own start. Never rely on "logged in at check N": a login session expires after a few idle minutes (5 by default here), and a human reading the checks takes longer than that, so a reused cookie fails with 401.
  - When a feature's behaviour hinges on a distinction (for example 401 vs 404 vs 403), give that distinction its own self-contained check that shows the cases side by side: the same request, with only the variable that matters changed. The human maintainer shouldn't have to piece it together from checks scattered through the plan, which relies on memory.
  - Name every id. Wherever a command uses an id, the check says what it is, in an **Acts on:** line: the organization's name, or whose membership or invitation it is (for example "the Avengers (`a0000000-…-001`)", "natasha's membership (`c0000000-…-011`)"). A bare UUID tells a human nothing.
- **Everything a check prints is human-readable.** The human maintainer's words: "what ever I read on the command line from human checks must be human readable". JSON always goes through `python3 -m json.tool`, including on a command that also shows its status code: `curl -s -w '%{stderr}%{http_code}\n' ... | python3 -m json.tool` prints the code on its own line, then the JSON one field per line (`%{stderr}` keeps the code out of the pretty-printer's input). Only a response with no body, such as a `204`, uses `curl -s -o /dev/null -w '%{http_code}\n'`. Never throw away a body the check's **Expect** line asks the reader to look at.

### 1.4 Git follows the README exactly

When committing, pushing or opening a PR, give the human maintainer the README's documented Commit Protocol as written (branch, `git add`/`git commit`, `gh pr create`, `gh pr merge --squash --delete-branch`). Don't add extra steps, elaborate heredoc bodies or inferred prerequisites. If a genuinely necessary step is missing, mention it briefly and mark it as an addition.

Every commit includes its release bookkeeping; a commit with only code is incomplete:
- a `CHANGELOG.md` entry, following its existing Keep a Changelog format and Semantic Versioning (a new version heading with a date and a short title, then `Added`/`Changed`/`Fixed` sections describing what changed and why)
- the version number in the commit message, as the README protocol shows (`feat(scope): brief description (vX.Y.Z)`)
- any other release step the README or a plan in `docs/plans/` documents

The AI agent drafts these alongside the code, for the human maintainer to review, rather than leaving them to be remembered at commit time.

**Never add AI attribution** to commit messages, PR titles or PR descriptions: no "Generated with …" line, no `Co-Authored-By` line for an AI agent, no mention of the AI tool. The human maintainer is the author and is accountable for everything that lands. This overrides any default attribution habit the AI agent's tool has.

Never bypass the repository's safeguards to get a commit or push through: no `--no-verify` to skip pre-commit hooks, no `--force` pushes, no skipping or silencing a failing check. When a hook or check fails, the failure is information; fix what it found. See 4.4.

---

## 2. Test-driven development (red, green, refactor)

### 2.1 Never write production code before its test

This is a codebase-wide rule with no feature boundary. Production code at any layer is never written before a test that exercises it exists and has been run to a confirmed failure. That includes entities, value objects, ports, adapters, commands, queries, HTTP routes, router registration and DI provider wiring.

The sequence for every step:

1. **Write the test file only.**
2. **Stop and hand over the command to run it.** The human maintainer runs it and confirms it fails for the expected reason: an import error, a missing attribute, a 404 or 405 from an unmounted route, or an assertion failing against behavior that isn't implemented yet. This is RED, and it has to be observed, not assumed.
3. **Only after RED is confirmed,** write the minimal production code that makes it pass, then hand over the command again for the human maintainer to confirm GREEN.
4. **Only after GREEN is confirmed,** refactor, keeping the tests green.

Never write a test and its production code back to back in the same turn.

The only exceptions:
- **Code that is genuinely not worth testing,** such as trivial one-line wiring with no behavior of its own. This is the human maintainer's call, never the AI agent's. The AI agent must not decide on its own that something is untestable.
- **An explicit green light from the human maintainer** for one specific piece of code.

**Test-support code is not itself tested.** Unit and integration tests are for application code. Seed scripts (`scripts/seed_db.py`) and test helpers are part of the testing *methods*, not application code: a seed script supports manual testing the way a fixture supports automated testing. Tests are not tested by other tests, and the same goes for seed scripts. They are written directly, without a RED/GREEN cycle.

**Ports are not exempt.** A Protocol port is introduced in the same TDD cycle as the first test that needs it: an adapter's integration test, or a consumer's unit test with a fake. The missing port is part of that test's RED. Never write a port as a standalone step "because it has no behavior".

### 2.2 Keep REDs simple, and never suppress tests

- **A RED must be a running test failure.** Never propose a RED that relies on mypy or any other step that stops the unit tests from running. The human maintainer's words: "Unit tests must always run, I don't want anything to suppress unit tests."
- **Design value objects before the entities that hold them.** An entity's first test should already expect the value object type (the way `User` has held `Username` from day one), so the RED is the ordinary "module or type doesn't exist yet" failure, and GREEN is creating the entity with the correct type. This is how the original author did it.
- **If a value object is retrofitted onto an existing field,** treat it as the simple change it is: update the tests to expect the value object, change the type and the mapping, and run the suite. Don't invent an elaborate RED for a type annotation.

### 2.3 New settings need a loader test

Every new environment-variable-driven setting needs two kinds of test:
1. the consuming code's own unit tests, using plain literal values for its internal logic
2. a dedicated `test_load_<name>_settings_reads_env_vars` test in `tests/unit/main/config/test_loader.py`, proving the settings loader actually reads the environment variable

A hardcoded literal in the consumer's tests alone leaves the environment-variable wiring completely unverified.

### 2.4 One continuous push, one micro-step at a time

For a large, multi-step plan, the human maintainer prefers one continuous session over splitting the work across several PRs or sessions, because an AI agent loses context between sessions. The discipline inside that push is still strict TDD: one step, one test, a confirmed RED, a confirmed GREEN.

---

## 3. Changing existing code

### 3.1 Additive building blocks only

Never tamper with existing code whose full consequences aren't understood. That especially means the original template author's code, and earlier features the human maintainer already built and trusts. New functionality is added as a self-contained building block on top of the existing composition, not by restructuring or reaching into it, even when the restructuring would preserve behavior and be technically cleaner.

- **The "feature delete" test:** it should be possible to delete what was just added and get the original composition back completely unaltered. If deleting the addition would also mean undoing changes to existing files, the work has strayed into risky territory.
- **Prefer a little duplication over editing an existing class** to fit a new use case. The model is domain events: a major feature added without altering what it was built on, and `WorkerProvider`, a new provider that leaves `CoreProvider` untouched.
- **The limit in the other direction:** separate providers (`WorkerProvider`, `PublicApiProvider`) exist only because those entrypoints needed different concrete bindings for the same port, which can't coexist in one Dishka container. When a feature runs in the same web process and just needs a few more bindings, appending those lines to `CoreProvider` in `main/ioc/core.py` is fine. Still flag it as a touch to an original file, and never restructure, split or reorder the existing bindings.
- **The one named exception:** a future move to a modular-monolith folder layout may *relocate* original-author files into per-bounded-context folders. That means moving files and updating import paths only, never rewriting or "improving" the moved code. It is a single decision the human maintainer made for that one change, not a precedent for touching the original author's code more freely elsewhere.

The reasoning: the original author's code is, right now, at the highest quality and the most battle-tested it will ever be. Every edit is a chance to introduce a regression into code that has none.

### 3.2 Keep the diff small

When editing an existing file, use targeted edits (one per site, or a replace-all for a truly uniform rename), not a full-file rewrite. A wholesale rewrite hides which lines actually changed and invites accidental drift. Full-file writes are for new files, or a rewrite the human maintainer asked for.

### 3.3 Don't rewrite human-authored comments or prose

When a change makes part of an existing comment or document stale, fix only the specific detail that changed, or add a small note next to it. Don't regenerate the surrounding human-written prose, even if the rewrite would also be accurate. Rephrasing text that was already correct risks introducing new, subtle errors.

### 3.4 Don't "correct" the original author's instructions

Never edit the original author's documented commands or setup steps (in `README.md` or similar) because they look like a bug, even when the reasoning seems solid. The original author has years of context an AI agent reading the code fresh doesn't have, and the original author often turns out to be right. Raise the discrepancy in conversation for the human maintainer to decide. New docs that describe the same command should mirror the author's text literally.

### 3.5 Audit privilege before sharing a capability across entrypoints

Before making a command work on another entrypoint (for example binding it into both `CoreProvider`, the cookie app, and `PublicApiProvider`, the API-key app) by pattern-matching a precedent like `GetOwnProfile`, check two things:
1. **Would it retire or touch an implementation that already works on either entrypoint?** If so, don't, unless there's a strong reason argued separately.
2. **Do that entrypoint's real use cases and privilege model justify the capability?** An API key is a narrow, programmatic credential. Letting a leaked key change the account's password, for example, is a far larger privilege than anything else that key allows.

---

## 4. Design principles

### 4.1 Smallest viable infrastructure by default

Every capability must work on the smallest viable infrastructure by default, which in practice is the web process plus Postgres. Heavier infrastructure (Redis, Celery workers, Elasticsearch) is an optional, switch-on upgrade behind the same port. Extra infrastructure costs real money, so it must never be mandatory for a core capability.

- **Define the port first.** Ship a default adapter that needs no new infrastructure (usually Postgres-backed), and make the heavier adapter a second implementation selected by configuration.
- **The default must be genuinely correct, not a toy.** An in-process memory rate limiter isn't shared across web workers, for instance, so a Postgres-backed counter is the honest default. Search defaults to Postgres full-text search, with Elasticsearch optional.
- **The model to copy is domain events:** handlers run inline with only the web process, or in the background via Celery and Redis when `CELERY_ENABLED` is on, through the same `EventDispatcher` and `EventHandler` ports either way.

### 4.2 DDD and Clean Architecture layering

Every implementation plan follows Domain-Driven Design and Clean Architecture layering: `core/common`, `core/commands`, `core/queries`, `inbound`, `outbound`, `main`. The CQRS import contracts enforced by `lint-imports` are respected; for example, `core.common` never imports commands or queries.

### 4.3 Naming in the DI layer

Classify which of three layers something sits in before naming it:
1. **Ports** stay generic: `IdentityProvider`, `AccessRevoker`.
2. **Concrete adapters** are named after their mechanism or strategy, not the entrypoint that uses them: `ApiKeyIdentityProvider`, `AuthSessionIdentityProvider`. A second mechanism then becomes a new sibling class, and the first class's name stays accurate.
3. **Composition-root providers** are named after the entrypoint or process they wire: `PublicApiProvider`, `CliProvider`, `WorkerProvider`.

### 4.4 Never take the path of least resistance

This codebase exists to solve small-scale architectural and complexity problems properly. Taking the path of least resistance is never the answer unless the human maintainer explicitly allows or asks for it. When the disciplined way and the quick way differ, take the disciplined way, or stop and ask.

Examples of what this rules out:
- forcing a commit or push past failing pre-commit hooks or checks (`--no-verify`, `--force`)
- skipping a test, or writing code before its test
- suppressing a type or lint error instead of fixing its cause
- weakening an assertion until it passes
- hardcoding a value that should come from configuration
- cutting a layer boundary "just this once"

TDD and the automated checks are core to this repository's design, so working around them works against the very thing the codebase is meant to demonstrate.

### 4.5 Build generic vertical slices, not business logic

Features in this codebase are comprehensive, production-ready vertical slices that many applications can build on: user-scoped, organization-scoped and notification use cases. Each slice is finished through every layer, with tests, error handling, authorization and documentation, rather than left as a demo.

- **Don't add any other vertical slice, or any business-specific logic** (rules, entities or workflows that only make sense for one kind of product), unless the human maintainer explicitly asks for it or has specified it in a plan in `docs/plans/`. A plan the human maintainer wrote or approved counts as specifying it; an AI agent's own suggestion doesn't count until the human maintainer approves it.
- **When an example resource is needed** to show a pattern (for instance a personal- versus organization-scoped CRUD resource), keep it deliberately generic, such as a "Project" or a "Note", and minimal.
- **Before proposing a feature,** check that it would be useful to many different applications. If it would only be useful to one product, it belongs in that product's fork, not here.
- **A slice includes seed data, not just tests.** Besides its unit, integration and smoke tests, every vertical slice adds development seed data to the database (via `scripts/seed_db.py`, keeping the existing generic superhero fixtures). A human reviewer or tester can then try the feature by hand, or demo it, straight after `make upd`, without first building up state themselves. Seed data covers the interesting cases, not just the happy path: for example an expired key as well as a valid one, or a pending invitation as well as an accepted membership. It pairs with the human-driven checks in 1.3, which should be runnable against the seeded data.

### 4.6 Every addition is a liability

Every line of code, every file, every document and every comment is a liability. Each one increases the surface area for bugs and complexity, and adds cognitive load for the human who has to review, understand and maintain it. The human maintainer's attention is the ultimate bottleneck of this whole way of working, more than an AI agent's speed or output, so information is added with care.

- **Before adding anything, ask whether it earns its place.** Does it make the system more correct, or make it easier for a human to understand? If not, leave it out.
- **Prefer the smallest change that fully solves the problem,** and the shortest wording that fully explains it. Remove what's redundant rather than piling on more.
- **Weigh it at review time too.** A large diff, a new file or a long explanation spends the human maintainer's attention, so it has to be worth that cost.
- **Being a liability doesn't mean "don't add".** Code is a liability too, and we still write it whenever a feature needs it. The point is to add deliberately, not to add less at all costs. Once a feature is decided, the code, tests, seed data and comments that feature needs are all worth their cost. Not all additions weigh the same: application logic carries the most risk, and comments the least, because they are not logic (see 5.1).

---

## 5. Code style

### 5.1 Comment liberally

Add explanatory comments wherever possible, in application code and test code alike, even for things a well-named identifier would normally make obvious. This intentionally departs from a sparse-comment default.

This doesn't conflict with 4.6. Once we decide to build feature X, the code for X is worth adding, and so are the comments that explain it. A comment is a liability like any other addition, but a smaller one than code, because it isn't application logic.

Code is the ideal form of documentation and of design intent. But code is best understood in relation to other code: the rest of its module, the port it implements, the use case that calls it. A reader meeting one function for the first time doesn't have that context yet. Comments supply it. They help a human understand a function before meeting the rest of its family of functions, which lowers the cognitive load of reading the code rather than adding to it.

### 5.2 Explain code before showing it

Whenever the AI agent proposes code for review, it explains what the code does in three places: in the code's own design and structure, in code comments, and in the chat message. The chat explanation comes *before* the diff, so the human maintainer never has to reverse-engineer intent from a wall of changed lines.

### 5.3 Exact-pin every dependency

Every dependency in `pyproject.toml`, runtime and dev groups alike, is pinned with `==`, never `>=`, matching the original author's convention. After `uv add`, immediately tighten the constraint to the exact version resolved in `uv.lock`. Check this whenever the dependency lists are touched.

### 5.4 Docker Compose variables always have a fallback

Every environment variable interpolated in `docker-compose.yml` uses `${VAR:-default}`, never a bare `${VAR}`. The default is the value that was hardcoded there before the variable existed, so a missing or incomplete `.env` degrades gracefully instead of producing a broken configuration.

### 5.5 Fix the content, not the linter config

When a linter or spellchecker flags a false positive, fix the content that triggered it (reword the prose, rename the identifier) rather than adding a new suppression or config file. A new config file is one more thing to maintain forever.

---

## 6. Plans and documentation

### 6.1 Plans live in `docs/plans/`

Implementation plans are saved as markdown under `docs/plans/`, following the established structure:
- a "Proposed Changes" section of numbered steps, each listing the test files to write first and the production files to change second
- a File Summary
- a Verification Plan: automated tests, architecture checks (`lint-imports`, `mypy`), and ending with the short list of simple human-driven checks from 1.3

Whenever an AI agent creates a plan, it always externalizes it as a file in `docs/plans/` so it survives across sessions. The plan file in this codebase is the single source of truth, not the ephemeral plan in the AI agent's own tools (such as a plan-mode draft or a to-do list), which disappears when the session ends. Read from the file and write updates to it, never to a draft held elsewhere or only in the conversation. Good test coverage is a stated goal of every plan, not an afterthought.

Two further sections belong in every plan where they apply, including older plans, retroactively:
- **User stories.** Any feature a person uses is framed as user stories ("As a <role>, I want <capability>, so that <benefit>"), each with a few concrete acceptance points. They go in one table, so a human can scan them easily: `| Story | As a | I want | So that | Acceptance criteria |`, one row per story, with a short numbered title and the criteria as short points separated by `<br>`. Purely internal features, such as infrastructure a user never touches directly, can say "not user-facing" instead.
- **Human checks.** A numbered, copy-pasteable list covering both the usual cases and the edge cases (see 1.3), so no one ever has to remember how to test a feature by hand. Use `curl` commands for HTTP features; for other kinds, the real command a person would run, such as a `make` target or the CLI. A plan with nothing a human can usefully check says so and has no such section.

### 6.2 Choosing and citing reference repositories

When researching a plan, take inspiration from code written by humans, and prefer the most trustworthy sources:
- **Human-written code whose commit history is mostly from before 2024**, before the wave of AI-generated code (roughly 2024 to 2026), is a premium source of knowledge.
- **Trust signals** such as forks, stars, a long commit history and several real contributors raise a repository's value as a reference.
- **Repositories that lean toward software structure and engineering principles** (clear layering, tests, explicit design decisions) are preferred over ones that put speed, convenience, feature count or MVP shortcuts first.

**For security questions, OWASP comes first.** The OWASP Cheat Sheet Series (https://cheatsheetseries.owasp.org) is the primary authority on software security in this codebase. Security research reads the relevant OWASP cheat sheets first, checks every recommendation in them against the design, and sides with OWASP where another source disagrees, unless there's strong evidence otherwise, stated explicitly.

When an external repository inspired a design decision, write it into the plan document next to the decision it informed, as a plain URL, so the rationale stays discoverable without chat history.

### 6.3 Keep the README checklist in sync with the roadmap

`README.md`'s TODO checklist mirrors `docs/plans/0-production-readiness-roadmap.md`. When an item is added to the roadmap, add the matching line to the README checklist in the same change. It should be a short summary ending "— see `docs/plans/0-production-readiness-roadmap.md`".

### 6.4 Wiki code blocks need a source link

In `docs/wiki/content/`, every code block quoted from the codebase must be immediately preceded by a real markdown link to the exact source file it came from. A mention in the page's `!!! sourcefiles` block, or a path comment inside the fence, doesn't count.

### 6.5 Never leak the private downstream fork

This repository is public and open source. A private downstream fork exists for a real business. That business's name, its industry and any domain-specific terms from it must never appear anywhere in this repository: code, comments, docs, plans, commit messages or PR descriptions. This applies even when the human maintainer has explained that domain in conversation for context. Illustrative examples stay generic (a "Project" or "Note" resource, a project-management app, superhero test fixtures).

---

## 7. Communicating with the human maintainer

The human maintainer usually works with AI agents in a terminal, where markdown renders only partially. Whatever the tool, write for that.

- **Write plain, absolute URLs** (`https://github.com/owner/repo`), never markdown `[label](url)` links. The terminal hides the URL behind the label, so the human maintainer can't click or verify it.
- **Avoid wide markdown tables.** Tables with many columns render unreadably in the terminal. Present comparisons as a per-item list: a heading line per item, then short "label: value" facts.

---

## 8. Conversation history and recall

An AI agent keeps no memory between sessions of its own. Sessions end, crash or get resumed, and context is lost each time. These rules keep that loss from costing the human maintainer work.

- **Know where your tool keeps its history.** Most AI coding tools save session transcripts or chat history to local files or to a history store the tool can read. The AI agent is responsible for knowing where its own tool keeps this, and how to read it with ordinary tools. It never claims that past sessions are impossible to retrieve without first checking.
- **Retrieve past messages immediately when asked.** When the human maintainer asks for messages from a previous session, for example after a crash or when resuming, the AI agent finds that session's history and retrieves the messages straight away. The previous session is usually the most recent one other than the current session. This is the standing exception to rule 1.1: the AI agent runs this retrieval itself.
- **"The exact text" means verbatim.** When asked to recall the exact text of an earlier message, fetch it word for word from the stored history, with the simplest single command or tool call that works. Never paraphrase, re-summarize or reconstruct it from memory, even if the message is still in view, because a paraphrase silently changes details the human maintainer relies on.
- **Summaries are not transcripts.** When a tool compresses or summarizes earlier context to make room, or a session is resumed from a summary, anything that needs exact detail (a decision, an error message, the wording of a rule) is checked against the stored history, the plan files in `docs/plans/`, or this document before it is relied on.
- **Durable knowledge goes into the repository.** Plans, decisions and rules that must survive a session are written to `docs/plans/` (see 6.1) and to this document, never kept only in the AI agent's context or private notes.

**Example, one tool's layout:** Claude Code stores each session as a JSONL file under `~/.claude/projects/<project-slug>/<session-id>.jsonl`, and a single command such as `jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text' <file>.jsonl` extracts its assistant messages. Other tools use different locations and formats; the rules above apply regardless.
