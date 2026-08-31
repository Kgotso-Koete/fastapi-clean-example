# Running Tests

!!! sourcefiles "Relevant Source Files/Folders"
    - [`Makefile`](../../../../Makefile) — `PYTEST_PATHS_*` variables, `test`/`check`/`check-ci`/`test-docker*` targets
    - [`docker-compose.test.yml`](../../../../docker-compose.test.yml) — the compose overlay `test-docker-app`/`test-docker-migrations` layer on top of `docker-compose.yml`
    - [`pyproject.toml`](../../../../pyproject.toml) — `[tool.pytest]` config (`testpaths`, `-mnot(slow)`, asyncio mode)
    - [`.github/workflows/ci.yaml`](../../../../.github/workflows/ci.yaml) — what CI (Continuous Integration) actually runs, in order
    - [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) — which of these targets run automatically as git hooks, and when

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## The three path groups

The [`Makefile`](../../../../Makefile) defines three named groups of pytest paths, and every test-running target is built out of one or more of them — nothing invokes `pytest tests/` directly against the whole tree:

```make
PYTEST_PATHS_LIGHT := \
	tests/sanity \
	tests/unit \
	tests/integration/no_infra
PYTEST_PATHS_APP_INFRA := \
	$(PYTEST_PATHS_LIGHT) \
	tests/smoke \
	tests/integration/with_infra
PYTEST_PATHS_MIGRATIONS := \
	tests/integration/migrations
```

`PYTEST_PATHS_APP_INFRA` is `PYTEST_PATHS_LIGHT` plus the two infrastructure-heavy tiers — it's a strict superset, not a separate list maintained by hand. `PYTEST_PATHS_MIGRATIONS` stands apart from both: it points at `tests/integration/migrations` (the Alembic "stairway" test, upgrading and downgrading through every revision — see [`test_stairway.py`](../../../../tests/integration/migrations/test_stairway.py)), which needs its own dedicated database service and deliberately isn't folded into either of the other two groups.

## Which target runs what

!!! figure "Every make target, the paths it runs, and what it needs from Docker"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph nodock["No Docker needed"]
            mtest["make test"]
            mcheck["make check"]
        end

        subgraph dock["Docker-backed"]
            mtestapp["make test-docker-app"]
            mmig["make test-docker-migrations"]
            mall["make test-docker"]
        end

        light["PYTEST_PATHS_LIGHT<br/>sanity + unit + integration/no_infra"]
        appinfra["PYTEST_PATHS_APP_INFRA<br/>LIGHT + smoke + integration/with_infra"]
        migpaths["PYTEST_PATHS_MIGRATIONS<br/>integration/migrations"]

        mtest --> light
        mcheck -->|"lint, then"| mtest

        mtestapp -->|"up: db_pg, redis, worker"| appinfra
        mmig -->|"up: db_pg only"| migpaths
        mall --> mtestapp
        mall --> mmig

        linkStyle default stroke-width:3px,stroke:#333333
        style nodock stroke-width:1px,stroke:#333333
        style dock stroke-width:1px,stroke:#333333
    ```

- **`make test`** runs `pytest -v $(PYTEST_PATHS_LIGHT)` plus coverage flags (`--cov=src --cov-report=term-missing --cov-report=html`) — no container, no `.env`, nothing beyond the local Python environment.
- **`make check`** runs the full [lint pipeline](code-quality-tools.md) first, then `make test`, then `uv run coverage html` — the target a developer runs before committing, entirely against the light tier.
- **`make test-docker-app`** brings up `db_pg`, `redis`, and `worker` via `$(DC_TEST_DOCKER)` (`docker-compose.yml` + `docker-compose.test.yml` together, under the isolated `$(PROJECT_NAME)-test` compose project), waits for them to report healthy (`--wait --wait-timeout 180`), then runs a disposable one-off `app` container (`docker compose run -T --name $(TEST_RUNNER) app pytest ...`) against `$(PYTEST_PATHS_APP_INFRA)` — the light tier *plus* `tests/smoke` and `tests/integration/with_infra`. It always tears the stack back down (`down -v --remove-orphans`) afterward, whether the run passed or failed, and copies the coverage data file out of the disposable container first.
- **`make test-docker-migrations`** is a second, separate compose cycle: it brings up only `$(MIGRATION_DB_SERVICE)` (`db_pg`), runs `$(PYTEST_PATHS_MIGRATIONS)` in a disposable runner with `--no-deps` (so it doesn't also start `redis`/`worker`, which the stairway test has no use for), and tears down the same way.
- **`make test-docker`** is just `test-docker-app` then `test-docker-migrations`, followed by merging the Docker-run coverage data into a second HTML (HyperText Markup Language) report (`htmlcov-docker/`), kept separate from `make test`'s own `htmlcov/`.

## Why `docker-compose.test.yml` exists as an overlay, not a separate stack

[`docker-compose.test.yml`](../../../../docker-compose.test.yml) doesn't define a parallel set of services — it only *overrides* fields on the services `docker-compose.yml` already defines, applied on top of it via `-f docker-compose.yml -f docker-compose.test.yml`:

```yaml
app:
  ports: !reset []
  build:
    args:
      - ENVIRONMENT=development
  environment:
    ALLOW_DESTRUCTIVE_TEST_CLEANUP: "1"

worker:
  build:
    args:
      - ENVIRONMENT=development
```

`ports: !reset []` drops the host-port publishing `docker-compose.yml` sets for local dev use (irrelevant, and a possible collision source, inside a disposable test run), `ENVIRONMENT=development` at build time ensures the test image has dev dependencies (`pytest`, etc.) installed regardless of what a developer's own `.secrets` sets `ENVIRONMENT` to for testing the app's *own* production-gating behavior, and `ALLOW_DESTRUCTIVE_TEST_CLEANUP: "1"` is what actually unlocks the `allow_destructive` fixture guard described in [Test Infrastructure & Fixtures](test-infrastructure.md) — set here so a developer doesn't have to remember to export it by hand before every `make test-docker` run.

## What CI actually runs, and what runs as a git hook

[`.github/workflows/ci.yaml`](../../../../.github/workflows/ci.yaml) runs exactly two steps after installing dependencies: `make check-ci`, then `make test-docker` (with `ALLOW_DESTRUCTIVE_TEST_CLEANUP=1` set at the job level instead of relying on the compose overlay, since the job runs on the bare runner, not inside the `app` container). `check-ci` is `check`'s CI-flavored twin — see [Code Quality Tools](code-quality-tools.md) for the difference.

!!! figure "When each target runs automatically, from a developer's own commit to CI"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph precommit["git commit (pre-commit stage)"]
            c1["make check<br/>(light tier only)"]
            c2["make pip-audit<br/>(non-blocking)"]
            c3["make wiki-build"]
        end

        subgraph prepush["git push (pre-push stage)"]
            p1["make test-docker<br/>(with_infra + smoke + migrations)"]
        end

        subgraph ci["GitHub Actions (every push/PR)"]
            g1["make check-ci"]
            g2["make test-docker"]
            g1 --> g2
        end

        precommit --> prepush --> ci

        linkStyle default stroke-width:3px,stroke:#333333
        style precommit stroke-width:1px,stroke:#333333
        style prepush stroke-width:1px,stroke:#333333
        style ci stroke-width:1px,stroke:#333333
    ```

    > Locally, [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) wires `make check`, `make pip-audit`, and `make wiki-build` to the default `pre-commit` stage, and `make test-docker` to the `pre-push` stage specifically — so the full Docker-backed suite only runs when pushing, not on every single commit, keeping the light, no-Docker tier as the fast feedback loop for everyday commits. CI then reruns both `make check-ci` and `make test-docker` regardless, as the final, environment-independent check before merge.

## Where to go next

- [Test Infrastructure & Fixtures](test-infrastructure.md) — what `tests/smoke` and `tests/integration/with_infra` actually need from the `db_pg`/`redis`/`worker` containers this page's targets bring up.
- [Code Quality Tools](code-quality-tools.md) — the lint pipeline `make check`/`make check-ci` run before ever reaching a test.
- [Quick Start with Docker](../getting-started/quick-start-docker.md) — the `Makefile`'s non-test targets (`make upd`, `make up`, ...) for running the app itself.
