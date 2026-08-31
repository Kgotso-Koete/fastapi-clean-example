# Integration Test Coverage Report

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — the `test-docker` target's `uv run coverage html --data-file=.coverage.docker -d htmlcov-docker` line
    - [`docker-compose.test.yml`](../../../../docker-compose.test.yml) — the compose overlay that actually provisions Postgres/Redis/worker for this run

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this actually is — and its one real limitation

`make test-docker` runs `tests/smoke` + `tests/integration/with_infra` (real Postgres, real Redis, a real `worker` container — see [Running Tests](running-tests.md)) with its own separate coverage data file (`.coverage.docker`, never merged with the plain `make check` run's `.coverage`), then writes a full, browsable report to `htmlcov-docker/index.html` at the repo root. The page below embeds that exact file directly.

Same caveat as [Unit Test Coverage Report](unit-coverage-report.md): `htmlcov-docker/` is a gitignored build artifact that only updates when you actually run `make test-docker` yourself, and doesn't exist at all on a fresh clone until then — unlike the [dependency graph](../architecture/layer-dependencies.md#the-real-import-graph-generated-from-the-code-itself)/[Complexity](../complexity.md) pages, this one isn't regenerated on every `make wiki-build`. Treat it as a snapshot of your last local `make test-docker` run.

<iframe class="coverage-report-frame" src="/generated/htmlcov-docker/index.html" title="Integration test coverage report (htmlcov-docker/index.html)"></iframe>

## Where to go next

- [Unit Test Coverage Report](unit-coverage-report.md) — the counterpart for `make check`'s fast, no-infrastructure test tiers.
- [Running Tests](running-tests.md) — exactly which test paths `make test-docker` runs, and why its coverage data stays separate from `make check`'s.
- [Test Infrastructure & Fixtures](test-infrastructure.md) — what `tests/integration/with_infra`/`tests/smoke` actually provision.
