# Version Control (Git)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`README.md`](../../../../README.md#how-to-commit) — the "How to Commit" section and "Pre-commit Hooks Summary" table this page expands on
    - [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) — every hook this repo runs, and which git stage each fires at
    - [`.github/workflows/ci.yaml`](../../../../.github/workflows/ci.yaml) — the GitHub Actions CI (Continuous Integration) pipeline
    - [`Makefile`](../../../../Makefile) — `check`, `check-ci`, `test-docker`, `wiki-build`, `pip-audit`, the targets the hooks/CI actually call
    - [`docs/plans/`](../../../../docs/plans/) — the numbered implementation-plan docs, one per feature

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

This page is the fuller, wiki-native version of `README.md`'s ["How to Commit"](../../../../README.md#how-to-commit) section: the same branch/commit/PR (Pull Request)/merge protocol, plus the actual mechanics behind it — why a direct commit to `main`/`master` is blocked, what each pre-commit/pre-push hook really runs, and how that overlaps (or doesn't) with what GitHub Actions CI (Continuous Integration) checks again on the server.

## The commit-to-merge flow

`README.md`'s ["How to Commit"](../../../../README.md#how-to-commit) section documents four steps: create a feature branch, commit with a [Conventional Commits](https://www.conventionalcommits.org/) message, open a PR via `gh pr create`, then squash-merge and delete the branch via `gh pr merge --squash --delete-branch`. The exact commands, copied verbatim — this is the actual protocol to run, not a paraphrase of it:

[`README.md`](../../../../README.md#how-to-commit) — step 1, create a feature branch:
```shell
git checkout -b feature/<short-description>
```

[`README.md`](../../../../README.md#how-to-commit) — step 2, stage and commit using [Conventional Commits](https://www.conventionalcommits.org/):
```shell
git add .
git commit -m "feat(scope): brief description (vX.Y.Z)"
```

[`README.md`](../../../../README.md#how-to-commit) — step 3, create a Pull Request via the GitHub CLI:
```shell
gh pr create --title "feat(scope): brief description" --body "Detailed explanation of changes."
```

[`README.md`](../../../../README.md#how-to-commit) — step 4, merge and delete the branch once approved:
```shell
gh pr merge --squash --delete-branch
```

That's the complete protocol as documented — four commands, nothing more. `git push` never appears as its own step: `gh pr create` pushes the current branch to the remote itself if it isn't already there.

Two local git hook stages sit inside that flow without changing its shape — a commit only succeeds once its pre-commit hooks pass, and a push only succeeds once its pre-push hook passes:

!!! figure "The commit-to-merge flow, with hook stages inline"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph local["Local machine"]
            branch["git checkout -b<br/>feature/&lt;short-description&gt;"]
            add["git add ."]
            commit["git commit -m<br/>'feat(scope): ... '"]
            push["git push"]
            branch --> add --> commit
        end

        subgraph github["GitHub"]
            pr["gh pr create"]
            ci["CI workflow runs<br/>(push + pull_request)"]
            merge["gh pr merge --squash<br/>--delete-branch"]
            pr --> ci --> merge
        end

        commit -->|"pre-commit hooks pass<br/>(code-check, pip-audit,<br/>wiki-build, typos, ...)"| push
        push -->|"pre-push hook passes<br/>(test-docker)"| pr

        linkStyle default stroke-width:3px,stroke:#333333
        style local stroke-width:1px,stroke:#333333
        style github stroke-width:1px,stroke:#333333
    ```

    > Nothing about this sequence is enforced by a single tool — it's the combination of `pre-commit`'s two hook stages (below) blocking bad commits/pushes locally, `no-commit-to-branch` blocking commits to `main`/`master`/`develop`/`dev` specifically, and the CI workflow re-running the same style of checks once the PR reaches GitHub.

## Pre-commit and pre-push hooks

[`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) sets `default_stages: [pre-commit]` — meaning every hook that doesn't explicitly override `stages:` fires on `git commit`, not `git push`. Only one hook in the whole file overrides that default:

```yaml
- id: test-docker
  name: test-docker (local)
  entry: make test-docker
  language: system
  stages: [pre-push]
  pass_filenames: false
  verbose: true
```

That's the entire pre-commit/pre-push split in this repo: every hook below runs at commit time except `test-docker`, which runs once, right before a `git push` actually leaves the machine. Because `pre-commit` treats `pre-commit` and `pre-push` as separate git hook types that must each be installed, `README.md`'s Prerequisites step, `pre-commit install --hook-type pre-commit --hook-type pre-push`, matters literally — running plain `pre-commit install` (no `--hook-type` flags) would only install the `pre-commit` hook type, and `test-docker` would silently never run at push time.

`README.md`'s own "Pre-commit Hooks Summary" table lists six hooks. The real file configures more than that — every hook actually declared, grouped by which repo they come from:

| Hook | Stage | Source | What it does |
|---|---|---|---|
| `code-check` | pre-commit | local (`Makefile`) | Runs [`make check`](makefile-commands.md) — Ruff lint+format (auto-fixing), `tombi` format+lint, `deptry`, `slotscheck`, `lint-imports`, `mypy --strict`, then the fast test suite. See [Code Quality Tools](../testing/code-quality-tools.md) for what each gate checks. |
| `pip-audit-local` | pre-commit | local (`Makefile`) | Runs `make pip-audit` — scans locked dependencies for known vulnerabilities; a finding only warns (stderr), never blocks the commit (see [Code Quality Tools](../testing/code-quality-tools.md)) |
| `wiki-build` | pre-commit | local (`Makefile`) | Runs `make wiki-build` (`mkdocs build`) — fails the commit if this documentation wiki itself doesn't build cleanly |
| `test-docker` | **pre-push** | local (`Makefile`) | Runs `make test-docker` — the full integration suite against real Postgres/Redis containers; see [Running Tests](../testing/running-tests.md) |
| `check-ast`, `check-case-conflict`, `trailing-whitespace`, `end-of-file-fixer`, `check-added-large-files`, `check-docstring-first`, `check-json`, `check-toml`, `check-yaml`, `detect-private-key`, `debug-statements`, `check-merge-conflict`, `mixed-line-ending` | pre-commit | [`pre-commit/pre-commit-hooks`](https://github.com/pre-commit/pre-commit-hooks) | Generic hygiene checks — valid Python syntax (parses to an AST (Abstract Syntax Tree)), no case-only filename clashes, no trailing whitespace, files end in a newline (skipped under `docs/`), no accidentally-committed large files, docstrings appear before code, JSON (JavaScript Object Notation)/TOML (Tom's Obvious, Minimal Language)/YAML (YAML Ain't Markup Language) files parse, no private key material, no stray `pdb`/`breakpoint()` calls, no unresolved merge-conflict markers, line endings normalized to LF (Line Feed) |
| `no-commit-to-branch` | pre-commit | [`pre-commit/pre-commit-hooks`](https://github.com/pre-commit/pre-commit-hooks) | Blocks a commit whose *current* branch is `develop`, `dev`, `master`, or `main` (`args: [--branch, develop, --branch, dev, --branch, master, --branch, main]`) |
| `typos` | pre-commit | [`crate-ci/typos`](https://github.com/crate-ci/typos) | Flags common spelling mistakes across code and docs |
| `yamlfmt` | pre-commit | [`google/yamlfmt`](https://github.com/google/yamlfmt) | Formats every `.yml`/`.yaml` file per [`.yamlfmt`](../../../../.yamlfmt)'s config |
| `shellcheck` | pre-commit | [`koalaman/shellcheck-precommit`](https://github.com/koalaman/shellcheck-precommit) | Lints the shell scripts under [`scripts/makefile/`](../../../../scripts/makefile/) (`--severity=warning`) |

> The `check-yaml` hook itself excludes `docker-compose.test.yml` and `mkdocs.yml` from its own YAML-validity check — both use YAML tags or merge syntax that hook's parser can't handle, per the `exclude` pattern in [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml).

## Where hooks and CI diverge

!!! figure "What each stage runs, and where it does or doesn't reach CI"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph precommit["pre-commit stage<br/>(git commit)"]
            codecheck["code-check<br/>(make check)"]
            pipaudit["pip-audit-local"]
            wikibuild["wiki-build"]
            stdhooks["check-ast, check-yaml,<br/>detect-private-key,<br/>trailing-whitespace, ..."]
            nocommit["no-commit-to-branch"]
            typos["typos"]
            yamlfmt["yamlfmt"]
            shellcheck["shellcheck"]
        end

        subgraph prepush["pre-push stage<br/>(git push)"]
            testdocker["test-docker<br/>(make test-docker)"]
        end

        subgraph ci["GitHub Actions CI<br/>(on: push, pull_request)"]
            checkci["make check-ci"]
            testdockerci["make test-docker"]
            checkci --> testdockerci
        end

        codecheck -.->|"same lint/type gates,<br/>non-mutating in CI"| checkci
        testdocker -.->|"same target"| testdockerci

        linkStyle default stroke-width:3px,stroke:#333333
        style precommit stroke-width:1px,stroke:#333333
        style prepush stroke-width:1px,stroke:#333333
        style ci stroke-width:1px,stroke:#333333
    ```

[`.github/workflows/ci.yaml`](../../../../.github/workflows/ci.yaml) triggers `on: [push, pull_request]` — every push to every branch and every pull request, not just ones targeting `main`/`master`. Its one job checks out the repo, installs Python 3.13 and `uv`, runs `uv sync --locked --group dev`, then two steps:

Relevant section of [`.github/workflows/ci.yaml`](../../../../.github/workflows/ci.yaml):

```yaml
- name: Check code
  run: make check-ci

- name: Test with Docker
  env:
    ALLOW_DESTRUCTIVE_TEST_CLEANUP: 1
  run: make test-docker
```

`make check-ci` is the non-mutating sibling of the `code-check` hook's `make check` — same lint/type/import gates, but failing instead of auto-fixing (see [Code Quality Tools](../testing/code-quality-tools.md) for the exact `check` vs. `check-ci` gate order). `make test-docker` is the identical target the `test-docker` pre-push hook already runs locally, just against a fresh CI runner.

That overlap is also where the real gap sits: CI never calls `make pip-audit` or `make wiki-build`, and it never runs `typos`, `yamlfmt`, `shellcheck`, or any of the generic `pre-commit-hooks` checks (`detect-private-key`, `check-yaml`, `trailing-whitespace`, and so on) — those exist **only** as local, opt-in pre-commit hooks. `README.md`'s own "Pre-commit Hooks Summary" table doesn't mention this gap either — it lists six hooks total (omitting `yamlfmt`, `shellcheck`, and the whole `pre-commit-hooks` set) and doesn't distinguish "runs locally" from "also re-checked in CI." In practice this means a contributor who commits with `git commit --no-verify` (or never ran `pre-commit install` at all) can push code that skips the dependency-vulnerability scan, the wiki build check, the spell-checker, YAML formatting, and shellcheck entirely — CI's two steps re-verify the lint/type/test gates, but nothing else on that list.

## Local guard vs. GitHub's own branch protection

`no-commit-to-branch` is a **client-side** git hook: it runs inside `pre-commit`, on the contributor's own machine, and only stops a commit if that person has `pre-commit` installed and hasn't bypassed it with `--no-verify`. It is not the same mechanism as GitHub's server-side branch protection (rules configured against a repository on github.com — e.g. requiring PR review or passing CI checks before a merge to `main` is allowed at all, enforced by GitHub's servers regardless of what any contributor has installed locally).

This repository has no file that configures that server-side protection — there is no `CODEOWNERS` file and no GitHub ruleset/branch-protection configuration checked into the repo (branch protection rules, when used, live only in a GitHub repository's own Settings UI, not as a versioned file). So the only enforced-in-this-repo guard against a direct commit to `main`/`master` is the local `no-commit-to-branch` hook above — real, but bypassable by anyone who skips or never installs `pre-commit`.

## Conventional Commits and versioning

`README.md`'s commit step asks for a [Conventional Commits](https://www.conventionalcommits.org/) message with a version suffix, e.g. `feat(scope): brief description (vX.Y.Z)`. This isn't just documentation — the repository's actual commit history follows it: `feat(docs): add self-hosted documentation wiki (v0.10.0) (#8)`, `feat(infra): add environment-aware deployment gating and service-name centralization (v0.9.0) (#7)`, `feat(events): add transactional outbox for background event dispatch (v0.8.0) (#6)`, and so on, each one a squash-merged PR (Pull Request) number.

## Plan docs: one per feature, numbered in implementation order

[`docs/plans/`](../../../../docs/plans/) holds one implementation-plan document per feature, numbered in the order the features were actually built: `0-production-readiness-roadmap.md` (the standing backlog, not a single feature), then `1-events.md`, `2-observability.md`, `3-celery-redis-events.md`, `4-transactional-outbox.md`, `5-self-hosted-docs-wiki.md`. Each numbered plan is what a feature branch is actually built against — see [TDD (Test-Driven Development, Red-Green-Refactor)](../testing/tdd.md) for how each plan's steps are written and executed, including the "TDD order" convention that page covers in full; this page doesn't re-explain it.

## Where to go next

- [Code Quality Tools](../testing/code-quality-tools.md) — the exact gates behind `make check`/`make check-ci`, which `code-check` and CI's "Check code" step both run.
- [TDD (Test-Driven Development, Red-Green-Refactor)](../testing/tdd.md) — how `docs/plans/*.md` steps are written and executed before a feature is committed.
- [Running Tests](../testing/running-tests.md) — what `make test-docker` (the `test-docker` pre-push hook and CI's "Test with Docker" step) actually runs.
