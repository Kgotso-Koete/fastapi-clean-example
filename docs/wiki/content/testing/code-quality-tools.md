# Code Quality Tools

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — `lint`, `check`, `check-ci`, `pip-audit` targets
    - [`pyproject.toml`](../../../../pyproject.toml) — `[tool.ruff]`, `[tool.deptry]`, `[tool.mypy]`, `[tool.slotscheck]`, `[tool.importlinter]` config sections
    - [`scripts/makefile/slotscheck.sh`](../../../../scripts/makefile/slotscheck.sh) — wraps `slotscheck` to surface the real traceback behind an import failure
    - [`scripts/makefile/pip_audit.sh`](../../../../scripts/makefile/pip_audit.sh) — wraps `pip-audit` as a non-blocking warning, not a hard failure
    - [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) — which of these run automatically, and when

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The `make check` pipeline

`make check` is `lint` followed by `test` followed by an HTML (HyperText Markup Language) coverage report. Every gate in `lint` runs in a fixed order, and — with one exception — a failure at any gate stops the pipeline before the next one runs:

!!! figure "make check / make check-ci as a sequence of gates"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        branch{"make lint/check<br/>vs. make check-ci?"}

        subgraph fixmode["make lint / make check (local dev)"]
            ruffcheckfix["ruff check --fix"]
            fmtfix["ruff format<br/>tombi format<br/>(both rewrite files)"]
            ruffcheckfix --> fmtfix
        end

        subgraph checkmode["make check-ci (CI)"]
            ruffcheckplain["ruff check"]
            fmtcheck["ruff format --check<br/>tombi format --check<br/>(fail, no rewrite)"]
            ruffcheckplain --> fmtcheck
        end

        tombilint["tombi lint"]
        deptry["deptry"]
        slotscheck["slotscheck<br/>(via wrapper script)"]
        lintimports["lint-imports<br/>(import-linter)"]
        mypy["mypy --strict"]
        test["test<br/>(PYTEST_PATHS_LIGHT)"]
        cov["coverage html"]

        branch --> ruffcheckfix
        branch --> ruffcheckplain
        fmtfix --> tombilint
        fmtcheck --> tombilint
        tombilint --> deptry --> slotscheck --> lintimports --> mypy --> test --> cov

        linkStyle default stroke-width:3px,stroke:#333333
        style branch stroke-width:1px,stroke:#333333
        style fixmode stroke-width:1px,stroke:#333333
        style checkmode stroke-width:1px,stroke:#333333
    ```

    > The branch is formatting mode, and it starts at the very first gate: `make lint` (and therefore `make check`) runs `ruff check --fix` and then `uv run ruff format`/`uv run tombi format` — all three *rewrite files in place* — because it's meant for a local dev loop where auto-fixing is exactly the point. `make check-ci` instead runs plain `ruff check` (`--fix` left off) and `ruff format --check`/`tombi format --check` — which fail loudly on anything not already formatted, rather than silently rewriting it, since CI (Continuous Integration) has no way to hand rewritten files back to the developer. Every gate from `tombi lint` onward — `deptry`, `slotscheck`, `lint-imports`, `mypy` — runs identically in both.

## What each gate actually checks

- **`ruff check` / `ruff check --fix`** — a large, explicitly curated rule selection in [`pyproject.toml`](../../../../pyproject.toml)'s `[tool.ruff.lint]` (`select = [...]`): flake8-bugbear, flake8-bandit (security), flake8-async, mccabe complexity, pep8-naming, pyupgrade, isort import sorting, and more. A handful of rules are explicitly disabled (`PLR0913`/`PLR0917` too-many-arguments, three cyrillic-ambiguity rules, `TC001`-`TC003` typing-only-import rules), and `tests/**` gets its own relaxations (`S101` assert, `PLR2004` magic values, `PT011` broad `pytest.raises`, ...) via `[tool.ruff.lint.per-file-ignores]` — a test file is allowed patterns production code isn't. `line-length = 120`, `target-version = "py313"`.
- **`ruff format`** — Ruff's own formatter (Black-compatible), configured for double quotes and `skip-magic-trailing-comma = false` in `[tool.ruff.format]`.
- **`tombi format` / `tombi lint`** — the same fix-vs-check split as Ruff, but for TOML (Tom's Obvious, Minimal Language) files (in practice, just `pyproject.toml` itself in this repo) — formatting and linting `[tool.ruff]`/`[tool.mypy]`/etc. the same way Ruff formats/lints Python.
- **`deptry`** — checks for dependency hygiene issues (unused imports of declared dependencies, missing dependencies actually imported, ...) rooted at `src`. `[tool.deptry]` explicitly ignores `DEP002` (unused dependencies) and `DEP003` (transitive dependencies) — this project accepts some slack here rather than chasing every declared-but-unused package.
- **`slotscheck`** — verifies every `__slots__`-declared class in `src/app/` actually behaves like it has slots (no accidental `__dict__` reintroduced by a base class, decorator, or mixin). Run via [`scripts/makefile/slotscheck.sh`](../../../../scripts/makefile/slotscheck.sh) rather than a bare `uv run slotscheck src` — the script `tee`s the real output to the terminal, then greps it for a `"Failed to import"` line and, if found, re-imports that exact module standalone (`python -c 'import importlib,sys; importlib.import_module(sys.argv[1])'`) so the *actual* import traceback surfaces, since slotscheck's own error message for a broken import is often too truncated to debug from directly. `[tool.slotscheck]` sets `strict-imports = true` and excludes the Alembic migration package (`^app\.outbound\.persistence_sqla\.alembic`) from consideration entirely.
- **`lint-imports`** — the `import-linter` contracts in `[tool.importlinter]`: the `layers` contract enforcing `main → inbound → outbound → core` (imports only ever point right, never back), plus four CQRS (Command Query Responsibility Segregation — see [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for the read/write split this enforces)-shape `forbidden` contracts keeping `app.core.common`/`app.core.commands`/`app.core.queries` from importing each other in disallowed directions, plus one keeping `app.outbound.auth_ctx` from reaching into `app.outbound.adapters`. See [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) for the full explanation of what this contract does and doesn't catch.
- **`mypy`** — `[tool.mypy]` runs with `strict = true` over `scripts`, `src`, and `tests` (Alembic excluded via `exclude`), plus extra opt-in checks (`redundant-expr`, `truthy-bool`, `unused-awaitable`, `ignore-without-code` — the last one meaning a bare `# type: ignore` with no specific error code is itself an error). The `pydantic.mypy` and `sqlalchemy.ext.mypy.plugin` plugins are both loaded, so Pydantic models and SQLAlchemy's declarative mappings get their own specialized type-checking beyond what plain mypy would infer.

## `pip-audit` — deliberately outside `make check`/`make check-ci`

`pip-audit` is its own `.PHONY` target, never invoked by `lint`, `check`, or `check-ci`, and CI (`.github/workflows/ci.yaml`) never calls it either — only `.pre-commit-config.yaml` wires it up, as a separate `pre-commit` hook running alongside `code-check`.

!!! figure "pip-audit's own script: a warning, never a hard failure"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        export["uv export --format<br/>pylock.toml -o tmp/pylock.toml"]
        audit["uv run pip-audit<br/>--locked tmp/"]
        found{"vulnerabilities<br/>found?"}
        warn["echo WARNING (stderr) --<br/>exit code still 0"]
        clean["exit code 0,<br/>no output"]

        export --> audit --> found
        found -->|"yes"| warn
        found -->|"no"| clean

        linkStyle default stroke-width:3px,stroke:#333333
        style found stroke-width:1px,stroke:#333333
    ```

    > [`scripts/makefile/pip_audit.sh`](../../../../scripts/makefile/pip_audit.sh) exports the locked dependency set to a `pylock.toml` in a temp directory (`uv export --format pylock.toml`) and runs `pip-audit --locked` against exactly that — checking real installed/locked versions, not just what's declared — but its final line is `|| echo "WARNING: pip-audit found vulnerabilities (non-blocking)" >&2`, meaning a vulnerability finding **never fails the hook**, only prints a warning to stderr. This is a deliberate choice: a security advisory landing on a pinned, already-working dependency shouldn't silently block every commit until someone has time to evaluate and upgrade it — the warning surfaces the finding without holding development hostage to it.

## Where to go next

- [Layer Dependencies & Import Rules](../architecture/layer-dependencies.md) — the full explanation of the `import-linter` contract `lint-imports` enforces here, including what it doesn't catch.
- [Running Tests](running-tests.md) — the `test`/`check-ci` targets these lint gates feed into, and what `make test-docker` adds on top.
- [TDD (Test-Driven Development, Red-Green-Refactor)](tdd.md) — how this project's own history uses `mypy`/tests together as the GREEN signal for a change.
