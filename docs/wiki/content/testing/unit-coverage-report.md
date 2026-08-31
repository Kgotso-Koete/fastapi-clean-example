# Unit Test Coverage Report

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — the `check` target's `uv run coverage html` line, which produces `htmlcov/`
    - [`pyproject.toml`](../../../../pyproject.toml) — the `[tool.coverage.report]` section (`show_missing`, `skip_empty`, `exclude_lines`)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this actually is — and its one real limitation

`make check` runs `tests/sanity` + `tests/unit` + `tests/integration/no_infra` (see [Running Tests](running-tests.md)) with `--cov=src`, then `uv run coverage html` writes a full, browsable coverage report to `htmlcov/index.html` at the repo root. The page below embeds that exact file directly — not a copy, not a re-generated summary.

Unlike the [dependency graph](../architecture/layer-dependencies.md#the-real-import-graph-generated-from-the-code-itself) and [Complexity](../complexity.md) pages, this isn't regenerated on every `make wiki-build` — `htmlcov/` is a gitignored build artifact that only updates when you actually run `make check` yourself, and doesn't exist at all on a fresh clone until then. Treat this page as a snapshot of your last local test run, not a live, always-current report.

<iframe class="coverage-report-frame" src="/generated/htmlcov/index.html" title="Unit test coverage report (htmlcov/index.html)"></iframe>

## Where to go next

- [Running Tests](running-tests.md) — exactly which test paths `make check` runs, and how that differs from `make test-docker`.
- [Integration Test Coverage Report](integration-coverage-report.md) — the counterpart for `make test-docker`'s real-Postgres/Redis test tiers.
- [Code Quality Tools](code-quality-tools.md) — where coverage sits in the rest of the `make check` pipeline.
