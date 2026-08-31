# Makefile Commands Reference

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — every target documented on this page lives here
    - [`scripts/makefile/`](../../../../scripts/makefile/) — the shell scripts most targets delegate to (`docker_env.sh`, `local_env.sh`, `migration.sh`, `pip_audit.sh`, `slotscheck.sh`, `docker_prune.sh`, `pycache_del.sh`)
    - [`scripts/dishka/plot_dependencies_data.py`](../../../../scripts/dishka/plot_dependencies_data.py) — what `make plot-data` actually runs
    - [`docker-compose.test.yml`](../../../../docker-compose.test.yml) — the extra compose file layered on top of `docker-compose.yml` for `make test-docker*`
    - [`env.example`](../../../../env.example) — `.secrets` is where `PROJECT_NAME`/`ENVIRONMENT`/`WIKI_PORT` get read from if set there instead

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

[Quick Start with Docker](../getting-started/quick-start-docker.md) and [Quick Start Locally](../getting-started/quick-start-local.md) each cover the handful of commands you need to get running at all. This page is the fuller reference: **every** real target in the `Makefile`, not just the getting-started subset, grouped the way the `Makefile` itself is organized into sections.

## How the targets relate to each other

Several targets aren't leaf commands — they call each other, either as Make prerequisites (`target: prerequisite`) or via `$(MAKE) other-target` inside their own recipe. Knowing this matters: running `make check-ci` runs `slotscheck` and `test` as part of it, not instead of them.

!!! figure "Every Makefile target, grouped by section, with real inter-target calls"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph safety["Safety"]
            pipaudit["pip-audit"]
        end

        subgraph quality["Code Quality"]
            lint["lint"]
            slotscheck["slotscheck"]
            check["check"]
            checkci["check-ci"]
        end

        subgraph testing["Testing"]
            test["test"]
            testdockerapp["test-docker-app"]
            testdockermig["test-docker-migrations"]
            testdocker["test-docker"]
        end

        subgraph docker["Docker"]
            dockerenv["docker-env"]
            localenv["local-env"]
            upd["upd"]
            up["up"]
            opendash["open-dashboards"]
            updlocal["upd-local"]
            uplocal["up-local"]
            down["down"]
            stopall["stop-all"]
            prune["prune"]
        end

        subgraph database["Database"]
            migration["migration"]
        end

        subgraph wiki["Wiki"]
            wikiserve["wiki"]
            wikibuild["wiki-build"]
            wikigenerate["wiki-generate"]
            wikifull["wiki-full"]
        end

        subgraph misc["Misc"]
            pycachedel["pycache-del"]
            tree["tree"]
            plotdata["plot-data"]
        end

        lint --> slotscheck
        check --> lint
        check --> test
        checkci --> slotscheck
        checkci --> test
        testdocker --> testdockerapp
        testdocker --> testdockermig
        upd --> dockerenv
        upd --> opendash
        up --> dockerenv
        updlocal --> localenv
        uplocal --> localenv
        migration --> localenv
        tree --> pycachedel
        wikiserve --> wikigenerate
        wikibuild --> wikigenerate
        wikifull --> testdocker
        wikifull --> wikigenerate

        linkStyle default stroke-width:3px,stroke:#333333
        style safety stroke-width:1px,stroke:#333333
        style quality stroke-width:1px,stroke:#333333
        style testing stroke-width:1px,stroke:#333333
        style docker stroke-width:1px,stroke:#333333
        style database stroke-width:1px,stroke:#333333
        style wiki stroke-width:1px,stroke:#333333
        style misc stroke-width:1px,stroke:#333333
    ```

    > Every arrow above is a real `$(MAKE) <target>` call or a Make prerequisite (`target: prerequisite`) taken directly from the `Makefile` — not an implied or approximate relationship. `check` and `check-ci` overlap (both eventually run `slotscheck` and `test`) but aren't the same thing: `check` is the fast local loop; `check-ci` additionally checks formatting/linting in "don't modify anything, just fail if it's wrong" mode (`ruff check` instead of `ruff check --fix`, `ruff format --check` instead of `ruff format`), which is what a CI (Continuous Integration) pipeline needs and a local dev loop doesn't.

## Configurable variables

These sit at the top of the `Makefile` and change several targets' behavior at once:

| Variable | Default | Used by |
|---|---|---|
| `PROJECT_NAME` | `APP_SERVICE_NAME` from `env.example`/`.secrets`, else the repo directory name | Every `docker compose -p $(PROJECT_NAME) ...` invocation |
| `ENVIRONMENT` | `ENVIRONMENT` from `env.example`/`.secrets`, else `development` | `upd` (whether to run `open-dashboards`) |
| `WIKI_PORT` | `WIKI_PORT` from `env.example`/`.secrets`, else `8001` | `wiki` (so it serves on the same port the `wiki` Compose service uses) |
| `INFRA_SERVICES` | `db_pg redis` | `upd-local`/`up-local` (which containers those start), `test-docker-app` |
| `INFRA_INIT_SERVICES` | *(empty)* | One-shot services that prepare `INFRA_SERVICES` before tests run — none defined yet in this project |
| `MIGRATION_DB_SERVICE` | `db_pg` | `migration`, `test-docker-migrations` |
| `STAIRWAY_TEST` | `tests/integration/migrations/test_stairway.py` | `migration` (runs it after generating a new revision) |
| `TEST_PROJECT` | `$(PROJECT_NAME)-test` | Every `test-docker*` target — an isolated Compose project name so test containers never collide with your normal dev stack |

## Safety

| Command | What it does | Notes |
|---|---|---|
| `make pip-audit` | Runs [`scripts/makefile/pip_audit.sh`](../../../../scripts/makefile/pip_audit.sh) to scan installed dependencies for known vulnerabilities | Not part of `lint`/`check` — run it separately, e.g. before a release |

## Code Quality

| Command | What it does | Notes |
|---|---|---|
| `make lint` | `ruff check --fix`, `ruff format`, `tombi format`, `tombi lint`, `deptry`, `slotscheck`, `lint-imports`, `mypy` | Mutates files (`--fix`, `format` without `--check`) — this is the "fix it for me" variant |
| `make slotscheck` | Runs [`scripts/makefile/slotscheck.sh`](../../../../scripts/makefile/slotscheck.sh) against `src` | Checks that classes using `__slots__` do so correctly; called by both `lint` and `check-ci` |
| `make test` | `pytest -v` over `tests/sanity`, `tests/unit`, `tests/integration/no_infra`, with coverage (`--cov=src`, terminal + HTML (HyperText Markup Language) report) | No containers needed — this is the fast, infra-free test subset; see [Testing → Running Tests](../testing/running-tests.md) |
| `make check` | `lint` then `test`, then `coverage html` | The everyday local gate: fast, mutates files freely, no Docker required |
| `make check-ci` | `ruff check` / `ruff format --check` (non-mutating), `tombi format --check`, `tombi lint`, `deptry`, `slotscheck`, `lint-imports`, `mypy`, then `make test`, then `coverage html` | The CI-safe variant of `check` — fails instead of auto-fixing; this is what a pipeline should run, not `check` |

## Testing

| Command | What it does | Notes |
|---|---|---|
| `make test` | See Code Quality above | Listed there since it's also invoked by `check`/`check-ci` |
| `make test-docker-app` | Spins up `INFRA_SERVICES` (+ `worker`) via `docker-compose.yml` + `docker-compose.test.yml`, then runs `pytest` (`tests/sanity`, `tests/unit`, `tests/integration/no_infra`, `tests/smoke`, `tests/integration/with_infra`) inside a throwaway `app` container, copies `.coverage` out, tears the stack down | Uses an isolated `$(TEST_PROJECT)` Compose project name so it never collides with a `make upd` stack already running |
| `make test-docker-migrations` | Spins up just `MIGRATION_DB_SERVICE`, runs `tests/integration/migrations` (the [stairway test](database-migrations.md#the-stairway-test)) inside a throwaway container, tears the stack down | Skips cleanly if `PYTEST_PATHS_MIGRATIONS` or `MIGRATION_DB_SERVICE` is unset |
| `make test-docker` | Runs `test-docker-app` then `test-docker-migrations`, then builds a combined `htmlcov-docker/index.html` report | This is the full "real Postgres/Redis" test run — see [Testing → Running Tests](../testing/running-tests.md) |

## Docker

| Command | What it does | Notes |
|---|---|---|
| `make docker-env` | Runs [`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh) — regenerates `.env` from `env.example` + `.secrets`, computes `COMPOSE_PROFILES` | Prerequisite of `upd`/`up`/`test-docker*`; rarely run by itself |
| `make local-env` | Runs [`scripts/makefile/local_env.sh`](../../../../scripts/makefile/local_env.sh) — same idea, but rewrites `POSTGRES_HOST`/`REDIS_HOST` to `127.0.0.1` for the local-app-process path | Prerequisite of `upd-local`/`up-local`/`migration`; see [Quick Start Locally](../getting-started/quick-start-local.md) |
| `make upd` | Regenerates `.env`, then `docker compose up -d --build --force-recreate` — starts every container whose profile is active, detached; opens dashboards afterward if `ENVIRONMENT=development` | The command covered in [Quick Start with Docker](../getting-started/quick-start-docker.md) |
| `make up` | Same as `upd`, but attached — logs stream to your terminal, `Ctrl+C` stops everything | |
| `make open-dashboards` | Opens every dev-only URL (Uniform Resource Locator) (Swagger, Adminer, Grafana, Prometheus, Flower, Redis Commander, this wiki, both coverage reports) in your browser via `xdg-open` | Called automatically by `upd` when `ENVIRONMENT=development`; every `xdg-open` failure is swallowed (`|| true`) so a headless/SSH (Secure Shell) session doesn't fail the whole command |
| `make upd-local` | Regenerates the local-path `.env`, then starts only `INFRA_SERVICES`/`INFRA_INIT_SERVICES` (`db_pg redis` by default), detached | Used with `uvicorn --reload` running directly on your host — see [Quick Start Locally](../getting-started/quick-start-local.md) |
| `make up-local` | Same as `upd-local`, but attached | |
| `make down` | `docker compose down` — stops and removes every running container for this project | `redis` occasionally needs this run twice before it's actually removed — a known, not-yet-diagnosed quirk tracked in the [production readiness roadmap](https://github.com/ivan-borovets/fastapi-clean-example/blob/master/docs/plans/0-production-readiness-roadmap.md) |
| `make stop-all` | `docker ps -q \| xargs -r docker stop` — stops **every** running container on your machine, not just this project's | Blunt-instrument command; reach for `make down` first unless you specifically need to stop unrelated containers too |
| `make prune` | Runs [`scripts/makefile/docker_prune.sh`](../../../../scripts/makefile/docker_prune.sh) | Cleans up dangling Docker resources (images/volumes/networks) this project has accumulated |

## Database

| Command | What it does | Notes |
|---|---|---|
| `make migration msg="<short description>"` | Starts `MIGRATION_DB_SERVICE` in an isolated `<dir>-migration` Compose project, runs `alembic upgrade head` then `alembic revision --autogenerate -m "<msg>"`, runs the stairway test (`STAIRWAY_TEST`) against the new revision, then tears the throwaway stack down | `msg` is required — the script exits with an error if it's missing; see [Database Migrations (Alembic)](database-migrations.md) for the full flow |

## Wiki

| Command | What it does | Notes |
|---|---|---|
| `make wiki-generate` | Runs [`scripts/wiki/dependency_graph.py`](../../../../scripts/wiki/dependency_graph.py) and [`scripts/wiki/complexity_report.py`](../../../../scripts/wiki/complexity_report.py) — regenerates the dependency-graph/complexity content this wiki transcludes | Prerequisite of both `wiki` and `wiki-build`; rarely run by itself |
| `make wiki` | `wiki-generate`, then `uv run mkdocs serve --dev-addr 127.0.0.1:$(WIKI_PORT)` | Live-reloading, on the host, no Docker — same content this page is part of; needs `uv sync --dev` done once |
| `make wiki-build` | `wiki-generate`, then `uv run mkdocs build` — one-shot static build to `site/` | Runs automatically as a pre-commit hook (`wiki-build` in [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml)) to catch a broken build before it's committed |
| `make wiki-full` | `test-docker`, then `wiki-generate`, then `mkdocs build`, then `mkdocs serve --dev-addr 127.0.0.1:$(WIKI_PORT)` | One-shot pipeline for verifying the wiki reflects current code end-to-end, instead of running `test-docker`/`wiki-generate`/`wiki-build`/`wiki` as separate one-off commands |

## Misc / Project Structure

| Command | What it does | Notes |
|---|---|---|
| `make pycache-del` | Runs [`scripts/makefile/pycache_del.sh`](../../../../scripts/makefile/pycache_del.sh) — deletes stray `__pycache__`/`.pyc` clutter | Called automatically before `tree` |
| `make tree` | `pycache-del` then plain `tree` | Quick visual of the repo layout with cache clutter removed first |
| `make plot-data` | `APP_LOGGING_LEVEL=CRITICAL uv run python scripts/dishka/plot_dependencies_data.py` | Generates the data behind this project's Dishka dependency-injection container visualization |

## Where to go next

- **New to this project and just need the handful of commands to get running?** [Quick Start with Docker](../getting-started/quick-start-docker.md) or [Quick Start Locally](../getting-started/quick-start-local.md).
- **Want the day-to-day Docker dev-loop story (live reload, rebuilding, shelling in), not just the command list?** [Docker Development Environment](docker-development.md).
- **Generating a migration with `make migration`?** [Database Migrations (Alembic)](database-migrations.md) covers exactly what that target does under the hood.
