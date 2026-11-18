# Working agreement: the human maintainer and AI coding agents

> **Every AI agent reads [`humans.md`](humans.md) at the start of every session, and whenever the human maintainer asks to resume a conversation, before anything else, then this document and [`README.md`](README.md), all three in full** (the last two added by the human maintainer on 2026-11-18). `humans.md` is the human maintainer's own account of how they learn and think. It explains why many rules below exist: human cognition is the true price, so an AI agent must never produce information, code or documents faster than the human maintainer can understand them.

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

The human maintainer runs every terminal command (shell, git, docker, make, uv, pytest, and so on) unless they explicitly say otherwise for a specific command. The AI agent does not run commands itself. It hands over the exact command to run, with a short explanation of what that command does, so the human maintainer understands it before running it. The explanation covers the syntax too, not only the overall effect: every flag and option (`--upgrade-package`, `-s`, `-w`), and every shell operator (`&&`, `|`, `$( )`, `<( )`) the command uses. The human maintainer's words: "always explain what a command does, including syntax and flags".

- This holds whatever permission or autonomy setting the AI agent's tool is running under. An auto-approving mode, or earlier commands in the same session that ran without objection, is never authorization to keep running commands. Such settings change how much the AI agent can decide without asking; they do not change who runs commands.
- Read-only commands (`ls`, `grep`, `cat`, `find`) are not exempt. To inspect the codebase, the AI agent uses its tool's built-in file-reading and search features, not shell commands.
- **When the human maintainer does authorize a specific command** ("run the command", "just do it"), the AI agent runs it immediately, in that same turn, with no re-explaining, hedging or second confirmation.
- **Every message that asks for commands carries the full list, in order.** Each command the human maintainer still has to run, plus the ones from the same step already run and shared, marked done, so nobody has to scroll back to track what is left. The human maintainer's words: "I don't have the mental bandwidth to scroll up and keep track of all the commands you ask me to run and the order to run them."
- **Every command stands on its own, in its own code block,** never inside a paragraph. Each gets a **Purpose** line (what running it achieves, why it's needed now in terms of the task, and where to run it when that matters, such as "in a second terminal, leave `make upd` running in the first") and a **Breakdown** of its syntax: every argument, flag and operator. The human maintainer's words: "Please make sure commands that I should run are in their own block and not tangled in a paragraph."
- **In chat, every command to copy sits between copy markers** (set by the human maintainer on 2026-11-15). The explanation comes first, then a `COPY FROM HERE ▼` line, the command alone, a `COPY TO HERE ▲` line, then what to expect. The markers show exactly what to copy even where the terminal doesn't render code fences.
- **Every value meant to be copied, pasted or typed sits on its own line, in its own code block,** never inside a sentence: commands, code, environment variables, usernames, passwords, ids, and the answer to any prompt. This holds in chat and in every document: the README, the wiki, plans, walkthroughs and human checks. A command that asks questions (a CLI login, for example) is followed by each prompt in the order it appears, with its answer in its own block. The human maintainer's words (2026-11-14): "Any code, command, environment variable, username, password, or other value meant to be copied and pasted should always be on its own line block and marked clearly in a code block so its visually distinct from other text."
- **Several commands come as numbered blocks, one per thing being checked** (set by the human maintainer on 2026-11-15). Each block tests one thing (for example the lint and type checks, one test file, or the Docker suite), sits between separator lines, and has a title saying what it checks, such as "BLOCK 2: organization invitation tests". Where the test runner offers both, a test block gives a verbose form first (every test by name, `-v`) and a summary form second (counts only, `-q`), each labelled, with a note that either one runs the same tests. Each command keeps its own Purpose, Breakdown and expected result.
- **Readable beats short** (set by the human maintainer on 2026-11-15). Write each command on its own line rather than folding several into a shell loop. The human maintainer copies and pastes either way, so readability is what matters.
- **A command that saves its output to a file writes it into the project's `logs/` folder,** never into the AI agent's own temporary or scratch space, so the human maintainer can open and examine it too. `.gitignore` ignores `logs/`, so nothing in it is ever committed. The human maintainer's words (2026-10-29): "These kinds of commands should rather write to the logs folder in this project because I should be able to examine them myself."
- **Every command's explanation says whether it changes files, and that is checked against the project's own configuration first.** A tool's defaults are not enough: this codebase's `pyproject.toml` sets `fix = true` and `unsafe-fixes = true` for ruff, so a plain `ruff check` rewrites files. A command meant only to report runs in its read-only form (`ruff check --no-fix`, `ruff format --diff` or `--check`), and is only called read-only once the configuration has been read. On 2026-10-29 the AI agent described a plain `ruff check` as changing nothing, and it rewrote two import blocks outside the step the human maintainer had approved; the human maintainer asked for this rule to be recorded here.
- **No next RED or GREEN while commands are outstanding.** The AI agent waits until the output of every command it asked for (tests above all) has been shared before proposing the next edit, so nothing is edited on top of an unverified step.
- **Never ask for an edit and for commands in the same message.** While an edit is waiting for approval, the message asks only for that approval. The human maintainer's words: "You asked me to make edits and you asked me to run commands in the same message. Which is it?"
- **Once the edits are approved and made, their verification commands follow straight away, in that same message.** The human maintainer approves each edit by reviewing its diff as it appears; right after the last edit, the AI agent gives the full command list to verify them. It never ends a message by saying the commands will come in a later one. The human maintainer's words (2026-10-28): "Please just send verification commands straight after I approve edits via my diff reviews. Don't wait by saying 'command X will come in my next message', and then I sit there waiting for your message that never comes."
- **When nothing is outstanding, the next proposal goes in the same message.** The AI agent never holds it back behind a redundant step, such as asking the human maintainer to look again at a diff they already reviewed as it was made. The human maintainer's words (2026-10-28): "Looked at what exactly?", then "Why did you wait to propose this?"
- **Hands-on instructions are numbered in the order the human maintainer carries them out, and every warning sits inside the step it applies to, before the action.** This covers anything done by hand: dragging folders, using the editor, a sequence of commands. Background goes before step 1, and nothing that has to be acted on comes after the last step. Before sending, the AI agent walks the steps as the human maintainer will: at each one, is everything needed right there? The human maintainer's words (2026-10-28), about a warning to decline VS Code's "Update imports" prompt that came in a list of notes after the drag step: "Putting this ... at the bottom of the sequence is a mistake; you can see that, right? What if I forget what I read towards the bottom of the list?"
- **Standing exception: fetching past conversation text.** When the human maintainer asks for messages from a previous session, or the exact text of an earlier message, the AI agent retrieves it itself straight away (see section 8).

### 1.2 Use the real entrypoint for verification

When giving manual verification steps, use the real top-level command a user or a deployment would run (a Makefile target, a documented script), not a hand-built sequence of its internal sub-steps. Example: `make down` then `make upd`, not `make docker-env` followed by `make upd`, because `upd` already depends on `docker-env`. Verification should exercise the whole real workflow, not an approximation that happens to reach the same state.

### 1.3 The verification ladder

- **RED step:** run the single test file, `uv run pytest <path> -v`, or `make test-docker` when the test needs real infrastructure. For a single infrastructure test file, `make test-docker-file path=<path>` runs just that file in the same throwaway Docker test stack, in a minute or two instead of the full suite. A RED has to be seen as a running test failure. `make check` stops at lint and mypy before any test runs, so it can't show a RED.
- **Only four commands run tests.** Each has one job:
  - `uv run pytest <path> -v`: one test file that needs no database, such as a RED or GREEN for a unit test. Runs on the computer directly, in seconds.
  - `make check`: everything that needs no database (lint, formatting, the import contracts, mypy, and every unit test). Runs on the computer directly, in about half a minute.
  - `make test-docker-file path=<path>`: one test file or folder that needs a real database, Redis or the worker (the `with_infra` tests). Starts its own throwaway Docker stack, runs just that path, then removes the stack. Takes a minute or two.
  - `make test-docker`: every test, including all the `with_infra` ones, in the same kind of throwaway stack. Takes about 10 minutes; runs at the end of each plan step and before every commit.
  - `unit=<name>` narrows `make check` or `make test-docker` to one unit's tests. It is a narrower form of those two commands, not a fifth one, and is for the human maintainer's quick feedback while working on one unit. The name is `base`, `shared` or a module's name (a folder under `tests/modules/`); any other name is refused before anything runs. It doesn't apply to `uv run pytest <path> -v` or `make test-docker-file path=<path>`, which already name what they run. For example:
    - `make check unit=organizations`: every linter over the whole app, then only `tests/modules/organizations/`'s light tests.
    - `make test-docker unit=organizations`: only `tests/modules/organizations/`'s unit and infrastructure tests, in the throwaway Docker stack, and no migration tests.
    - `make test-docker unit=base`: only `tests/base/`'s tests, including the whole-app suites (characterisation, sanity, smoke and migrations).
    - `make check unit=shared`: every linter, then only `tests/shared/`'s light tests.

    The AI agent's GREEN and end-of-step commands are always the full ones, without `unit=`: a unit's own tests can't show what its change breaks in another unit. For a GREEN, `make check`, never `make check unit=organizations`; at the end of a step, `make test-docker`, never `make test-docker unit=organizations`.

  **The problem this prevents:** a `with_infra` test needs Postgres, Redis and a worker. Run with plain `uv run pytest` on the computer, it has none of them, so it fails with connection errors that say nothing about the code. The tempting workaround is to start the development stack first (`make upd`) and point the tests at it. But then the human maintainer has to manage ports, environment variables and a stack running alongside their other apps, and the tests run against the development database, the one holding the seed data the human checks rely on, and empty its tables.

  **The rule:**
  - never `uv run pytest` on the computer against `with_infra` tests;
  - never `make upd` (or any other start-up) so that tests can reach a database;
  - a test that needs infrastructure always runs through `make test-docker-file` or `make test-docker`, whose throwaway stack is created, used and removed by the command itself.
- **GREEN step:** run `make check`, not just `uv run pytest tests/base/unit`. `make check` covers everything the narrower command does and more (ruff format and lint, the import-linter layer and CQRS contracts, mypy, then the light test paths). It catches a GREEN whose tests pass but that breaks a type, a layer contract or formatting.
- **Anything touching infrastructure (Postgres, Redis, Celery, the worker):** run `make check`, then `make test-docker`, and only then do manual checks (`make upd` and inspection). Don't skip the automated integration tier. While iterating on one step, `make test-docker-file path=<path>` may confirm its RED and GREEN; the full `make test-docker` still runs before every commit and before the manual checks.
- **How often the full `make test-docker` runs** (decided by the human maintainer on 2026-11-04, because the full run takes about 10 minutes):
  - a TDD cycle whose change no running entrypoint reaches yet (for example a pure function nothing imports at run time): `make check` only;
  - a cycle that changes what a running entrypoint does (DI wiring, routes, event handlers, the worker): `make check`, then `make test-docker-file path=<path>` on the affected test folders;
  - the end of each plan step, before its human checks, and before every commit: one full `make test-docker`.
- **The final and ultimate check: simple, human-driven, common-sense verification.** Automated tests prove what they were written to prove. The last rung is a small list of manual checks the human maintainer can do and see for themselves, without complex container workflows or reading test output:
  - a request from Postman or the browser
  - an AI-assisted `curl` command
  - looking at the response or the page
  - confirming it matches what a user would expect

  Every feature's verification plan ends with such a list. Keep it short (a handful of checks) and concrete: the exact request, and what a correct result looks like, so anyone can sense-check it in a few minutes.
- **Seed data comes before the human check, not after it.** Most human checks run against data the seed script (`scripts/seed_db.py`) has already created: named accounts, organizations, roles and every interesting state (pending, expired, accepted, and so on). The human maintainer creates only a little data by hand, to exercise the create/update/delete paths themselves. So whenever a slice becomes reachable by a human (its routes exist), the seed data for it is added in that same step, before the human check is handed over. It is never deferred to the end of the plan. An AI-assisted human check that makes the human build all the test data from scratch has missed the point.
- **Human checks are written down in the feature's plan, as copy-pasteable `curl` commands.** Each check is a numbered item in a "Human checks" section of that feature's plan in `docs/plans/`. It gives the exact, human-readable `curl` command (with a login step and one cookie file per user where needed), which seeded account it acts as, and the expected status and message. The checks live in the plan, not only in chat, so they survive between sessions and can be re-run at any time. Seeded rows the checks act on get fixed ids, so the commands can be pasted as written.
- **Human checks follow a user's journey through the user stories** (set by the human maintainer on 2026-11-15). Each journey names the user stories it proves, by ID (6.1), and its steps are the actions those stories describe, in the order the actor takes them. The real clients come first: `curl` and Swagger UI for this API today, the browser once a frontend exists. A step that stands in for what a person can't make happen on demand (a delay, an expiry, another party's schedule) sits inside its story's journey and says what it stands in for. A check that only exercises a function or a row, with no actor doing anything a story describes, belongs in the unit or integration tests.
- **Human checks wait until a domain's journeys are built** (set by the human maintainer on 2026-11-15). A domain's checks are handed over only once every story its journeys rely on has its RED and GREEN done, so the human maintainer checks each journey once, for correctness and completeness together, instead of coming back to it as pieces land.
- **The human checks have a clear start and end** (set by the human maintainer on 2026-11-15). The plan's "Human checks" section opens with a line saying the checks start there, and closes with "Human checks end here.", so nothing a human runs is mixed into planning text. Inside, in this order: setup, seeded data, who can do what, then the checks, grouped by feature and numbered. Each check's title states its expected result, for example "A MEMBER can't invite: 403, and nothing stored".
- **Human checks spend the scarcest resource: the human maintainer's time and attention.** They focus on what the automated tests can't show: the real running app, worker and CLI; stored data read back with raw SQL; real runs of the project's own tooling; and checks that change code and put it back (for example, deregistering a module, seeing the app still start, then registering it again). Edge cases belong here when no test can reach them.
  - Checks that repeat what unit or integration tests already prove are kept to a minimum: 5 to 15 in a plan. Each one is chosen with care, for behaviour important enough to be worth seeing with your own eyes. The human maintainer may ask for a few more, as `curl` commands, when they want them.
  - Checks reuse the running stack and the data earlier checks created. A step doesn't stop and rebuild the stack (`make down`, `make upd`) just to recreate data; a query filters to the rows that matter instead.
  - `curl` and raw SQL are welcome as helpers: to seed the data a check needs, to fill in a long form without a UI, or to look rows up with a filter.

  The human maintainer's words (2026-11-14): "Human checks are the most expensive resource because the humans time is most expensive. ... Human checks should be focused on very essential things to verify including edge cases but they should not go on forever."
- **Human checks are exact and unambiguous: no placeholders, ever.** The human maintainer's words: "No placeholder values, please; it makes life hard for no reason. No ambiguity."
  - Every login is written out as its own command, with the real username and password, right before that user's first request. Never "log in as X first" without the command.
  - No `<id>`, `<username>` or similar to fill in. A value only known at run time (such as a new row's id) is captured into a shell variable by the command that creates it, then reused as `$VARIABLE`.
  - No "re-run check N" or "run it again": repeat the command in full where it's needed, so the checks read top to bottom in the order they're run.
  - **Every step carries the state it needs** (set by the human maintainer on 2026-11-15). An **Expect** line spells out the exact values to look for, never "the result from check 3". When a command returns several rows, it says how many, which one the step is about (by a value the reader can see) and what the others are. A step that repeats an earlier request to show nothing changed repeats the earlier result in full.
- **Every human check explains what it's testing and why.** A short title like "A MEMBER can't invite" isn't enough. Each check gets a **Why** line: the rule being tested (for example "inviting needs at least ADMIN"), why the rule exists, and why this status code rather than a similar one (for example 403 rather than 404). A feature with roles or permissions also gets a short "who can do what" reference before its checks. The human maintainer's words: "The more I know what I am testing against, the easier it is."
- **Every command in a human check explains itself, in the plan.** Like the commands the AI agent hands over in chat (1.1), each command written into a plan's human checks says what it does and what every flag, option and operator in it means (for `curl`, for example, `-sS`, `-w '%{stderr}%{http_code}\n'`, `-c` and `-b`, `-X`, `-H`, `-d`, and the pipe into `python3 -m json.tool`), so the reader never has to scroll back to an earlier explanation. The human maintainer's words (2026-11-14): "human checks with curl commands should always explain what the curl commands do including what command flags mean".
- **Every `curl` in a human check is readable at a glance** (set by the human maintainer on 2026-11-15). One request per code block, introduced by a short sentence saying who acts and what the request does, and followed by its **Expect** line. The URL stays on the first line, and each further option (`-H`, `-d`, `-b`, `-c`) goes on its own line, joined with a trailing ` \`. A JSON body that needs shell values is built with `jq -n --arg name "$VALUE" '{...}'`, never with escaped quotes (`\"`). When two requests differ in one value, both are written out in full and the text says which value changed. Long checks are run from the plan file, not pasted from chat, where a line-ending backslash can be lost.
- **Prove every assumption with a command before relying on it.** If a check depends on a starting state ("peter is a MEMBER of the Avengers", "diana's invitation has expired", "this id is matt's invitation"), it first runs a read-only command that shows that state, before the command under test. The same goes for the result: a check that changes something ends with a command that shows the change, rather than trusting the status code. The human maintainer's words: "These types of assumptions should have a curl command to demonstrate that he is a member before we can show that he can't invite anyone because he is not an ADMIN." Pipe JSON through a pretty-printer (`python3 -m json.tool`) so it's easy to read.
  - Each check proves its *own* starting state, right before its command under test, even if an earlier check already showed it. Never write "check N proved…": the human maintainer shouldn't have to remember what an earlier check printed.
  - Each check logs in every user it acts as, at its own start. Never rely on "logged in at check N": a login session expires after a few idle minutes (5 by default here), and a human reading the checks takes longer than that, so a reused cookie fails with 401.
  - When a feature's behaviour hinges on a distinction (for example 401 vs 404 vs 403), give that distinction its own self-contained check that shows the cases side by side: the same request, with only the variable that matters changed. The human maintainer shouldn't have to piece it together from checks scattered through the plan, which relies on memory.
  - Name every id. Wherever a command uses an id, the check says what it is, in an **Acts on:** line: the organization's name, or whose membership or invitation it is (for example "the Avengers (`a0000000-…-001`)", "natasha's membership (`c0000000-…-011`)"). A bare UUID tells a human nothing.
- **Everything a check prints is human-readable.** The human maintainer's words: "Whatever I read on the command line from human checks must be human-readable.". JSON always goes through `python3 -m json.tool`, including on a command that also shows its status code: `curl -s -w '%{stderr}%{http_code}\n' ... | python3 -m json.tool` prints the code on its own line, then the JSON one field per line (`%{stderr}` keeps the code out of the pretty-printer's input). Only a response with no body, such as a `204`, uses `curl -s -o /dev/null -w '%{http_code}\n'`. Never throw away a body the check's **Expect** line asks the reader to look at.
- **A documented command that fails is fixed in the document itself.** When a command in a plan's human checks or in the README turns out to be broken, or to hide an error, the AI agent proposes the fix to that document first, rather than handing over one-off workaround commands in chat. A documented command survives failure: it prints the status code and the whole error body, never a traceback. The human maintainer's words (2026-11-03): "You should be fixing the problematic command in the documentation itself; the documentation lives longer than this chat session."
- **Show whole objects, never a few picked fields.** A command that prints only selected fields (`print(u["username"], u["role"])`) hides the rest, and a wrong value in a hidden field goes unnoticed. To narrow a list to the rows a check is about, filter the rows but print each one whole, as pretty JSON: `python3 -c 'import sys, json; print(json.dumps([u for u in json.load(sys.stdin)["users"] if u["username"] == "peter-parker"], indent=4))'`. A count (`len(...)`) is fine as an extra line next to the whole object, for something a human can't count by eye, never instead of it. The human maintainer's words: "These types of commands hide other fields from the user object. It's always better to see the entire object."

### 1.4 Git follows the README exactly

When committing, pushing or opening a PR, give the human maintainer the README's documented Commit Protocol as written (branch, `git add`/`git commit`, `gh pr create`, `gh pr merge --squash --delete-branch`). Don't add extra steps, elaborate heredoc bodies or inferred prerequisites. If a genuinely necessary step is missing, mention it briefly and mark it as an addition.

**A commit closes a whole plan** (ideally, and unless the human maintainer says otherwise), after its human checks pass, never a single TDD step. The human maintainer's words: "Human checks are what make a commit legitimate."

Every commit includes its release bookkeeping; a commit with only code is incomplete:
- a `CHANGELOG.md` entry, following its existing Keep a Changelog format and Semantic Versioning (a new version heading with a date and a short title, then `Added`/`Changed`/`Fixed` sections describing what changed and why)
- the version number in the commit message, as the README protocol shows (`feat(scope): brief description (vX.Y.Z)`)
- any other release step the README or a plan in `docs/plans/` documents

The AI agent drafts these alongside the code, for the human maintainer to review, rather than leaving them to be remembered at commit time.

**Never add AI attribution** to commit messages, PR titles or PR descriptions: no "Generated with …" line, no `Co-Authored-By` line for an AI agent, no mention of the AI tool. The human maintainer is the author and is accountable for everything that lands. This overrides any default attribution habit the AI agent's tool has.

Never bypass the repository's safeguards to get a commit or push through: no `--no-verify` to skip pre-commit hooks, no `--force` pushes, no skipping or silencing a failing check. When a hook or check fails, the failure is information; fix what it found. See 4.4.

### 1.5 Every file change is asked for first, and shown as a diff

Whenever the AI agent wants to create, edit or update a file, it asks the human maintainer's permission first, unless the human maintainer has said it may work autonomously. The human maintainer's words: "Whenever you want to edit/update/create a file, always ask me for permission unless I give you permission to work autonomously."

- **Every change is made so the human maintainer sees the diff:** with the AI agent's tool's own file-editing feature, which shows the exact lines removed and added. Never by running code that rewrites files (a `python3` script, `sed -i`, a heredoc redirected into a file, and so on), which hides the change. The human maintainer's words: "Always edit/update/create the file by showing me the diff instead of you running code in your internal tools to create/edit files."
- **A change that touches many files is made file by file, never with one blanket command.** For a rename or a move across the codebase, the AI agent never hands over a `grep | xargs sed -i`, or anything else that rewrites many files at once, however carefully filtered. Instead, the human maintainer writes the list of affected files to a file the AI agent can read. The AI agent then reads and edits each file with its own editing feature, in small batches the human maintainer reviews, and stops at any line that isn't the expected change. Re-running the list after each batch shows what is left. A check over the whole diff at the end proves nothing else changed. The human maintainer's words (2026-10-29): "Why not systematically list every Python file and step through each file and examine the imports? What if something goes wrong with this blanket command? Let's rather have surgical manual precision than use a power drill and screw things up."
- **Before asking, the AI agent says what it will change and why** (see 5.2), so the permission is an informed one.
- **Permission is asked per TDD step, not per edit:** once for a RED (the tests it adds and what each one proves) and once for a GREEN (the code change that makes them pass). With a yes, the AI agent makes all of that step's edits straight away, each shown as a diff, without asking again file by file. The same goes for a non-code step, such as a docs update. The human maintainer's words: "Just ask permission for a red or a green edit/creation, and explain what change you propose for a red or green. Then jump straight to the red or green change where I see the diff."
- **A request to write RED or GREEN code is marked clearly, at the bottom of the message** (set by the human maintainer on 2026-11-18). It comes after everything else in the message (research, explanations), under its own heading, such as `PERMISSION NEEDED: RED`, so it can't be missed. The human maintainer's words: "a question you have about code to RED/GREEN TDD code should be marked clearly, preferably at the bottom of your text message in our chat. It's easy to miss your request to add RED/GREEN TDD code."
- A request from the human maintainer that names the change ("update agents.md with…", "fix that test") is that permission, for that change only.
- **Autonomous work starts only when the human maintainer says "start".** Being keen to grant autonomy, or choosing an option, is not the go-ahead. The human maintainer's words (2026-10-17): "I will tell you when to start working autonomously."
  - **Autonomous work keeps the RED/GREEN Test-Driven Development (TDD) cadence** (section 2). Wherever possible the AI agent writes the RED test first and runs it to see it fail, then writes the GREEN code and runs the tests to see it pass, and then verifies with the post-GREEN checks (1.3). It runs as many TDD cycles as the objective the human maintainer set out requires.
  - **A design, architecture or engineering question pauses autonomous work.** The AI agent stops, asks the human maintainer the question, and waits for the answer before resuming.
  - **What autonomous work runs, and what it still hands over** (set by the human maintainer on 2026-11-15). The AI agent runs its own RED and GREEN test commands (`uv run pytest <path> -v`, `make check`, `make test-docker-file path=<path>`). The full `make test-docker` before human checks and commits, `make migration`, dependency installs, and every `git` and `gh` command are still handed over to the human maintainer.

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

**Test-support code is not itself tested.** Unit and integration tests are for application code. Seed scripts (`scripts/seed_db.py`) and test helpers are part of the testing *methods*, not application code: a seed script supports manual testing the way a fixture supports automated testing. Tests are not tested by other tests, and the same goes for seed scripts. They are written directly, without a RED/GREEN cycle. That includes a module's own seed data in its `main/seed.py` (`docs/plans/16-modular-monolith.md`, Step 4g); only the registry wiring that lists it (a unit's `SEEDS`) is tested, like a unit's routes or table mappings. The human maintainer's words (2026-11-11), after an AI agent proposed a database test for the seed script: "Seed data should be simple and trustworthy enough that we don't need unit tests for it."

**Never break application code to prove a test can fail.** No mutation checks: no temporarily weakening a policy, editing production code or regenerating a migration just to watch a test go red. Tests exist to report the health of the app; tests that need their own tests bring back the problem TDD solves. The human maintainer's words: "Otherwise we need tests for our unit tests and that causes problems that TDD is supposed to solve in the first place."
- **Design the test so only the mechanism under test can produce its result.** For example, a test that a policy's `WITH CHECK` refuses an `INSERT` uses no `RETURNING`, because with `RETURNING` the `SELECT` policy can raise the same error.
- **Where doubt remains, prove the mechanism by hand** as a human check: raw SQL in the database shell, as the role in question.

**Ports are not exempt.** A Protocol port is introduced in the same TDD cycle as the first test that needs it: an adapter's integration test, or a consumer's unit test with a fake. The missing port is part of that test's RED. Never write a port as a standalone step "because it has no behavior".

### 2.2 Keep REDs simple, and never suppress tests

- **A RED must be a running test failure.** Never propose a RED that relies on mypy or any other step that stops the unit tests from running. The human maintainer's words: "Unit tests must always run; I don't want anything to suppress unit tests."
- **Design value objects before the entities that hold them.** An entity's first test should already expect the value object type (the way `User` has held `Username` from day one), so the RED is the ordinary "module or type doesn't exist yet" failure, and GREEN is creating the entity with the correct type. This is how the original author did it.
- **If a value object is retrofitted onto an existing field,** treat it as the simple change it is: update the tests to expect the value object, change the type and the mapping, and run the suite. Don't invent an elaborate RED for a type annotation.

### 2.3 New settings need a loader test

Every new environment-variable-driven setting needs two kinds of test:
1. the consuming code's own unit tests, using plain literal values for its internal logic
2. a dedicated `test_load_<name>_settings_reads_env_vars` test in `tests/base/unit/main/config/test_loader.py`, proving the settings loader actually reads the environment variable

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
- **The one named exception: the modular monolith restructuring** (`docs/plans/16-modular-monolith.md`). It is the only time this codebase makes major changes to the original author's code. The human maintainer's words: "This is the only time I am giving us permission to break this rule." Within that one change:
  - original-author files are *relocated* under one prefix, `src/app/base/`, with nothing below it changing (only code added since, Organizations, Notifications' handlers and the email adapters, moved into `src/app/modules/` and `src/app/shared/`): files move and import paths change, and the moved code is never rewritten or "improved";
  - the composition code that names every piece by hand (the DI providers, the routers, the table mappings) may be changed so it builds the app from a registry of modules;
  - any new code the restructuring needs is test-first (section 2); only pure moves are exempt;
  - every known behaviour is the same afterwards, and it starts from a codebase in a clean state: everything committed, nothing half-done.

  It is not a precedent for touching the original author's code more freely anywhere else, before or after.

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
- **A slice includes seed data, not just tests.** Besides its unit, integration and smoke tests, every vertical slice adds development seed data to the database (via `scripts/seed_db.py`, or a module's own `main/seed.py`, keeping the existing generic superhero fixtures). A human reviewer or tester can then try the feature by hand, or demo it, straight after `make upd`, without first building up state themselves. Seed data covers the interesting cases, not just the happy path: for example an expired key as well as a valid one, or a pending invitation as well as an accepted membership. It pairs with the human-driven checks in 1.3, which should be runnable against the seeded data.

### 4.6 Every addition is a liability

Every line of code, every file, every document and every comment is a liability. Each one increases the surface area for bugs and complexity, and adds cognitive load for the human who has to review, understand and maintain it. The human maintainer's attention is the ultimate bottleneck of this whole way of working, more than an AI agent's speed or output, so information is added with care.

- **Before adding anything, ask whether it earns its place.** Does it make the system more correct, or make it easier for a human to understand? If not, leave it out.
- **Prefer the smallest change that fully solves the problem,** and the shortest wording that fully explains it. Remove what's redundant rather than piling on more.
- **Weigh it at review time too.** A large diff, a new file or a long explanation spends the human maintainer's attention, so it has to be worth that cost.
- **Being a liability doesn't mean "don't add".** Code is a liability too, and we still write it whenever a feature needs it. The point is to add deliberately, not to add less at all costs. Once a feature is decided, the code, tests, seed data and comments that feature needs are all worth their cost. Not all additions weigh the same: application logic carries the most risk, and comments the least, because they are not logic (see 5.1).

### 4.7 No application or security logic in generated files

Application and security logic never lives in a folder of generated files, such as Alembic's `versions/`, unless the human maintainer advises otherwise. A person debugging a design or security issue looks in the application code, not in a folder of files a tool wrote. The human maintainer's words: "It never makes sense to write application/security logic in a folder that is generated by code (like Alembic migrations)."

- **The source of truth is readable application code,** such as the SQLAlchemy mappings for tables, or a module declaring roles, grants and Row-Level Security policies.
- **Generated files are snapshots of that source,** written by the tool: `make migration` turns the source into a migration, the way it turns a mapping into `CREATE TABLE`. When the tool can't yet express something (grants, RLS, policies), extend the generator so it can, rather than hand-writing the logic into the generated file.
- **A generated file never imports the live source.** Old migrations must stay frozen; if they imported a module that later changes, they would silently change what they do.
- **A migration is only ever created with `make migration msg="..."`,** run by the human maintainer. It spins up a throwaway database, generates the revision from the mapping (with a real revision id and parent), and runs the stairway test. The AI agent changes the mapping first, hands over the command, then reads the generated file. It never writes a migration by hand.

### 4.8 Before 1.0.0, no code to carry data across an upgrade

Until this codebase reaches version 1.0.0, no deployment depends on rows surviving an upgrade. Development databases and Docker volumes are dropped and recreated routinely, and tables and their relations keep changing through migrations. So no permanent code is written to handle temporary data from before a change: no mapping of old import paths in outbox rows or queued Celery messages, no compatibility shims for old row formats, no "drain first" deploy procedures. When a change leaves such data behind, the CHANGELOG entry says so in one line, and that's all. The human maintainer's words (2026-10-30): "During active pre-launch development (before version 1.0.0), we should not make permanent code changes to accommodate temporary complexity from requiring rows to survive an upgrade until this code is ready for that."

- **This does not cover migrations.** Schema changes still go through `make migration` and the stairway test, as always (4.7); this rule is only about rows already written under an older shape or path.
- **It ends at 1.0.0,** when the human maintainer decides that upgrades must preserve data. That decision is recorded here when it is made.

### 4.9 Folder names communicate architecture

Folder structure and file locations carry meaning. A naming or mirroring rule (such as plan 16's "new path = unit folder + old path") is a safe default, never a reason to produce a path a human can't read, such as `modules/organizations/inbound/http/organizations/`. Before proposing where a file goes, the AI agent reads the full path as a newcomer would; if a folder name repeats its parent or says nothing new, it says so and offers a name that describes the folder's role. It keeps following the rule by default and presents the readability cost honestly, rather than arguing for the rule; only the human maintainer decides an exception. The human maintainer's words (2026-11-09): "Things being mirrored should not come at the cost of file organization communicating architecture semantically. The folder structure and file locations have meaning." And: "We will keep this as a safety measure, but I and I alone will advise when to break the rules."

### 4.10 Use cases drive every design, and decisions come one at a time, scored

Set by the human maintainer on 2026-11-15, in light of `humans.md`: direction beats speed, and their long-term fitness comes first.

- **Every design proposal starts with one line naming the use case it serves,** and how it moves the feature toward its goal. If that line can't be written, say so instead of proposing.
- **A new party, role or kind of thing is raised in chat, in plain words, before it goes in any document,** never added quietly to a plan.
- **Decisions are short and taken one at a time,** not long option lists the human maintainer has to cross-check against a plan.
- **Every option states its short-term and long-term trade-offs, and a score out of 10** for long-term maintainability, flexibility, scalability and readiness to manage complexity.
- **Options are real alternatives to each other.** Each is a different answer to the same question, never "option 1 plus an add-on"; an add-on worth weighing is its own decision, asked after the first.

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

An upgrade is always written down with its exact version, never left only in `uv.lock`. A package this codebase only uses indirectly (one that arrives through another dependency) is upgraded with an exact pin in `[tool.uv] constraint-dependencies`, with a comment saying why, not with `uv lock --upgrade-package` alone, and not as a direct dependency it doesn't import.

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

Whenever a plan records a test result (a RED, a GREEN, or a run of several suites), it gives the exact command that produced it, copied as it was run, next to the result (set by the human maintainer on 2026-11-15). A result without its command can't be re-run or checked.

Whenever an AI agent creates a plan, it always externalizes it as a file in `docs/plans/` so it survives across sessions. The plan file in this codebase is the single source of truth, not the ephemeral plan in the AI agent's own tools (such as a plan-mode draft or a to-do list), which disappears when the session ends. Read from the file and write updates to it, never to a draft held elsewhere or only in the conversation. Good test coverage is a stated goal of every plan, not an afterthought.

Two further sections belong in every plan where they apply, including older plans, retroactively:
- **User stories: the north star of every feature's design, and its status tracker** (set by the human maintainer on 2026-11-15, replacing the stories table each plan used to hold). Every feature is designed from its user stories first ("As a <actor>, I want <capability>, so that <benefit>"), each with concrete acceptance criteria; the plan follows from them. Purely internal features, such as infrastructure no actor touches, can say "not user-facing" instead.
  - **Their own file:** `docs/plans/user-stories/<plan number>-<topic>-user-stories.md`, listed with its feature code in `docs/plans/user-stories/README.md`. Every plan links to its stories file in a short section near its top and never copies the stories, so there's one source and nothing drifts.
  - **One HTML table that stands on its own,** so it can be copied or sent as a snapshot of where the feature stands. The model is `docs/plans/user-stories/9-organizations-user-stories.md`. Top to bottom: the title; the feature code, plan and snapshot date; the goal; key rows (how to read an ID, the hierarchy, a note that story terms are not code terms, the actors, the status marks, the kinds of test); the columns ID, As a, I want, So that, Acceptance criteria, Developed, Tests passing, Human checks, Committed; the stories; and bottom rows defining each kind of test and a human check.
  - **The hierarchy:** feature → domain (an area of the product) → actor → journey (a goal the actor pursues) → action (one story), in the order the actor takes the steps. Each domain ends with a "No story here yet" row naming the actors it has no story for, so a gap is visible.
  - **IDs:** `<feature code>.D<domain>.<actor>.J<journey>.A<action>`, such as `ORG.D2.US.J3.A2`. An ID never changes once written; a new action takes the next free number. Stories are cited by ID in plans, human checks, code comments and test docstrings.
  - **Actors** are defined in each file's key rows. A new actor is raised in chat before it goes in any document (4.10).
  - **A promise not to do something is a story too,** such as "an organization I don't belong to looks as if it doesn't exist". Smaller edge cases go in the acceptance criteria of the story they belong to. Out-of-scope items are not stories; they go in the plan's "Deliberately out of scope" list.
  - **The status columns** (Developed, Tests passing, Human checks, Committed) are updated after each GREEN and before each commit.
  - **Tests passing is counted, never typed:** passed/run by kind, such as `12/12 (BU), 9/9 (BI)`. The backend's kinds, named from the test's folder: **BU** unit, **BI** integration, **BS** sanity, **BSm** smoke; a frontend adds **FU** unit, **FI** integration and **FE** end-to-end. A kind a story has no tests of shows `0/0` for that kind in red text, such as `0/0 (BI)` for a story with no integration test (set by the human maintainer on 2026-11-18). Red is for those `0/0` counts only, and the rule stays even when every story has its tests (`docs/plans/user-stories/README.md`). Each test names the story it proves with the `story` marker registered in `pyproject.toml`: `@pytest.mark.story("ORG.D2.US.J3.A2")` on a test or class, or `pytestmark = pytest.mark.story(...)` for a whole file; a test proving two stories carries both. At the end of every run, `tests/conftest.py` prints each story's counts, and the column is copied from a full `make test-docker` run. A new test names its story in its RED.
  - **Tests mirror the code; user stories cut across it** (set by the human maintainer on 2026-11-15). Tests stay organised by the code they test, one use case, entity, value object, adapter or route each, so a RED points at exactly one piece of code and the test folders mirror the code folders. Stories and code map many to many (one use case can serve several actions), so the `story` markers are what connect them, and the counts per story are a gap detector: a story with no tests of a kind, such as no integration test, is always flagged as a gap. Tag an adapter test with the story whose acceptance criterion it most directly protects. Two refinements:
    - **A few journey tests per domain:** an integration test that walks a whole journey through the real stack (for example invite, accept, then listed as a member), carrying every story on its path. It catches breakage between steps that one-route tests miss, and is the automated twin of a journey-based human check: a handful per domain, not one per story.
    - **Counts show quantity, not completeness:** a story can have many tests and still miss an acceptance criterion, so when a plan is written, each story's acceptance criteria are checked against its tests.
  - **Every story is covered by at least one human check,** which follows that story's journey (1.3) and whose **Why** line cites the story's ID.
- **Human checks.** A numbered, copy-pasteable list covering both the usual cases and the edge cases (see 1.3), so no one ever has to remember how to test a feature by hand. Use `curl` commands for HTTP features; for other kinds, the real command a person would run, such as a `make` target or the CLI. A plan with nothing a human can usefully check says so and has no such section.

### 6.2 Choosing and citing reference repositories

When researching a plan, take inspiration from code written by humans, and prefer the most trustworthy sources:
- **Human-written code whose commit history is mostly from before 2024**, before the wave of AI-generated code (roughly 2024 to 2026), is a premium source of knowledge.
- **Trust signals** such as forks, stars, a long commit history and several real contributors raise a repository's value as a reference.
- **Repositories that lean toward software structure and engineering principles** (clear layering, tests, explicit design decisions) are preferred over ones that put speed, convenience, feature count or MVP shortcuts first.
- **Research means reading the code, not the metadata.** Stars, forks and dates only make the shortlist. Before a design is treated as settled, the reference repositories are downloaded into the git-ignored `ai_research/` folder (with the human maintainer's approval each time) and their code and structure are studied. A design drafted from general knowledge is labelled unresearched. The human maintainer's question (2026-10-17): "Did you download the good reference GitHub repos, study their code, study their structure and understand how it works?"

**For security questions, OWASP comes first.** The OWASP Cheat Sheet Series (https://cheatsheetseries.owasp.org) is the primary authority on software security in this codebase. Security research reads the relevant OWASP cheat sheets first, checks every recommendation in them against the design, and sides with OWASP where another source disagrees, unless there's strong evidence otherwise, stated explicitly.

When an external repository inspired a design decision, write it into the plan document next to the decision it informed, as a plain URL, so the rationale stays discoverable without chat history.

**External services' behaviour is cited, never assumed** (set by the human maintainer on 2026-11-15). When a plan relies on how an external service or library behaves (an email provider, a cloud API, a framework's documented behaviour), the AI agent reads its official documentation first, and puts an absolute, deep link to the exact section next to each fact the plan relies on. Anything the docs don't state is marked as such and becomes a check in the plan, never a guess written as fact.

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
- **Explain simply** (set by the human maintainer on 2026-11-15). Say in plain words what a tool or step does before using its jargon, keep explanations short, and prefer one concrete example over a general description. Break an idea into a handful of parts, a level or two deep, as `humans.md` asks.

---

## 8. Conversation history and recall

An AI agent keeps no memory between sessions of its own. Sessions end, crash or get resumed, and context is lost each time. These rules keep that loss from costing the human maintainer work.

- **Know where your tool keeps its history.** Most AI coding tools save session transcripts or chat history to local files or to a history store the tool can read. The AI agent is responsible for knowing where its own tool keeps this, and how to read it with ordinary tools. It never claims that past sessions are impossible to retrieve without first checking.
- **Retrieve past messages immediately when asked.** When the human maintainer asks for messages from a previous session, for example after a crash or when resuming, the AI agent finds that session's history and retrieves the messages straight away. The previous session is usually the most recent one other than the current session. This is the standing exception to rule 1.1: the AI agent runs this retrieval itself.
- **"The exact text" means verbatim.** When asked to recall the exact text of an earlier message, fetch it word for word from the stored history, with the simplest single command or tool call that works. Never paraphrase, re-summarize or reconstruct it from memory, even if the message is still in view, because a paraphrase silently changes details the human maintainer relies on.
- **Summaries are not transcripts.** When a tool compresses or summarizes earlier context to make room, or a session is resumed from a summary, anything that needs exact detail (a decision, an error message, the wording of a rule) is checked against the stored history, the plan files in `docs/plans/`, or this document before it is relied on.
- **A recap reads everything it names, and asks first when it can't reach something.** When the human maintainer asks for a recap of files or folders (such as `ai_research/<plan>/`), the AI agent reads all of it: that research was saved precisely so it could be re-read after a session ends. If its tools can't list a folder's contents, it asks for permission to list it at the start of the recap (or hands over the command), and never reads only the files it already knows about. The human maintainer's words (2026-10-29): "When I ask you to recap, it means we already read the research in the past ... You can clarify upfront to get permission to go into the folder and read it, and I will grant you the permission."
- **Durable knowledge goes into the repository.** Plans, decisions and rules that must survive a session are written to `docs/plans/` (see 6.1) and to this document, never kept only in the AI agent's context or private notes.

**Example, one tool's layout:** Claude Code stores each session as a JSONL file under `~/.claude/projects/<project-slug>/<session-id>.jsonl`, and a single command such as `jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text' <file>.jsonl` extracts its assistant messages. Other tools use different locations and formats; the rules above apply regardless.
