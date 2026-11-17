# Shell / Make config
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

.SILENT:
MAKEFLAGS += --no-print-directory

# -----------------------------
# User-configurable variables (edit this)
# INFRA_SERVICES: long-running infra (db, broker, cache, ...)
# INFRA_INIT_SERVICES: one-shot services that prepare INFRA_SERVICES
# MIGRATION_DB_SERVICE: transactional db service used by alembic (empty = no migrations)
# STAIRWAY_TEST: path to stairway test (empty = skip stairway step)
# -----------------------------
# Reads APP_SERVICE_NAME from env.example/.secrets directly (not .env,
# which may not exist yet on a first run) -- falls back to the directory
# name, the original default, if it's not set in either file.
PROJECT_NAME ?= $(or $(shell grep -h '^APP_SERVICE_NAME=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),$(notdir $(abspath .)))
# Same read pattern as PROJECT_NAME above -- used to skip open-dashboards
# (see `upd` below) when this isn't a dev deployment.
ENVIRONMENT ?= $(or $(shell grep -h '^ENVIRONMENT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),development)
# Every dashboard `open-dashboards` knows, by name; each name's URL is the
# DASHBOARD_URL_<name> variable defined below the port variables.
DASHBOARDS := docs public-docs adminer coverage coverage-docker grafana prometheus metrics flower redis-commander wiki
# Which of DASHBOARDS to open, as a comma-separated list (env files have no
# arrays): e.g. "docs,grafana,wiki". An EMPTY value means none, so this
# can't use the $(or ...) fallback above, which treats empty as unset:
# it falls back to every dashboard only when no OPEN_DASHBOARDS line exists
# at all in env.example/.secrets.
OPEN_DASHBOARDS ?= $(shell line=$$(grep -h '^OPEN_DASHBOARDS=' env.example .secrets 2>/dev/null | tail -1); \
	if [ -n "$$line" ]; then echo "$${line#*=}"; else echo "$(DASHBOARDS)"; fi)
# Same read pattern again -- so `make wiki` (plain `mkdocs serve`, no Docker)
# serves on the same port as the `wiki` Compose service, instead of
# mkdocs' own default (8000, which collides with `app`'s host port during
# `make upd`, which is why the Compose service uses this port instead).
WIKI_PORT ?= $(or $(shell grep -h '^WIKI_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),8001)
# Same read pattern again, one per dashboard `open-dashboards` (see `upd`
# below) opens -- so it always points at the actually-configured host port
# instead of a hardcoded default that silently diverges once a port is
# overridden in env.example/.secrets.
UVICORN_PORT ?= $(or $(shell grep -h '^UVICORN_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),8000)
ADMINER_PORT ?= $(or $(shell grep -h '^ADMINER_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),8080)
GRAFANA_PORT ?= $(or $(shell grep -h '^GRAFANA_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),3000)
PROMETHEUS_PORT ?= $(or $(shell grep -h '^PROMETHEUS_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),9090)
FLOWER_PORT ?= $(or $(shell grep -h '^FLOWER_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),5555)
REDIS_COMMANDER_PORT ?= $(or $(shell grep -h '^REDIS_COMMANDER_PORT=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2),8081)
# One URL per name in DASHBOARDS (see OPEN_DASHBOARDS above).
DASHBOARD_URL_docs := http://127.0.0.1:$(UVICORN_PORT)/docs
DASHBOARD_URL_public-docs := http://127.0.0.1:$(UVICORN_PORT)/public/docs
DASHBOARD_URL_adminer := http://localhost:$(ADMINER_PORT)
DASHBOARD_URL_coverage := http://127.0.0.1:5500/htmlcov/index.html
DASHBOARD_URL_coverage-docker := http://127.0.0.1:5500/htmlcov-docker/index.html
DASHBOARD_URL_grafana := http://localhost:$(GRAFANA_PORT)
DASHBOARD_URL_prometheus := http://localhost:$(PROMETHEUS_PORT)
DASHBOARD_URL_metrics := http://localhost:$(UVICORN_PORT)/metrics
DASHBOARD_URL_flower := http://localhost:$(FLOWER_PORT)
DASHBOARD_URL_redis-commander := http://localhost:$(REDIS_COMMANDER_PORT)
DASHBOARD_URL_wiki := http://localhost:$(WIKI_PORT)
# OPEN_DASHBOARDS as a space-separated list, so $(foreach) can walk it.
COMMA := ,
OPEN_DASHBOARD_LIST := $(strip $(subst $(COMMA), ,$(OPEN_DASHBOARDS)))
INFRA_SERVICES ?= db_pg redis
INFRA_INIT_SERVICES ?=
MIGRATION_DB_SERVICE ?= db_pg
STAIRWAY_TEST ?= tests/base/integration/migrations/test_stairway.py

# -----------------------------
# Internal vars / aliases
# -----------------------------
DOCKER_COMPOSE := docker compose -p $(PROJECT_NAME)
PIP_AUDIT := scripts/makefile/pip_audit.sh
SLOTSCHECK := scripts/makefile/slotscheck.sh
DOCKER_ENV := scripts/makefile/docker_env.sh
LOCAL_ENV := scripts/makefile/local_env.sh
DOCKER_PRUNE := scripts/makefile/docker_prune.sh
PYCACHE_DEL := scripts/makefile/pycache_del.sh
MIGRATION := scripts/makefile/migration.sh
DISHKA_PLOT_DATA := scripts/dishka/plot_dependencies_data.py

# Test stack is isolated by project name
TEST_PROJECT ?= $(PROJECT_NAME)-test
DC_TEST_DOCKER := docker compose \
	-p $(TEST_PROJECT) \
	-f docker-compose.yml \
	-f docker-compose.test.yml
TEST_RUNNER := $(TEST_PROJECT)-runner

# Pytest paths
# Every module's tests are picked up by wildcard, so a module added under
# tests/modules/<name>/ needs no edit here (docs/plans/16-modular-monolith.md,
# user story 5). shared's tests, under tests/shared/, are picked up the same
# way. wildcard lists only folders that exist.
PYTEST_PATHS_LIGHT := \
	tests/base/characterisation \
	tests/base/sanity \
	tests/base/unit \
	tests/base/integration/no_infra \
	$(wildcard tests/modules/*/unit) \
	$(wildcard tests/shared/unit)
PYTEST_PATHS_APP_INFRA := \
	$(PYTEST_PATHS_LIGHT) \
	tests/base/smoke \
	tests/base/integration/with_infra \
	$(wildcard tests/modules/*/integration/with_infra) \
	$(wildcard tests/shared/integration/with_infra)
PYTEST_PATHS_MIGRATIONS := \
	tests/base/integration/migrations
# unit=<name> narrows the three lists above to one unit's tests
# (docs/plans/16-modular-monolith.md, O6): base, shared or a module's name,
# e.g. `make check unit=organizations` or `make test-docker unit=base`. It keeps
# only the folders under that unit's own test folder (tests/base/,
# tests/shared/ or tests/modules/<name>/), so a unit's run is always part of
# the full run, and a new module needs no edit here. The linters in
# `make check` still run over everything: the import rules are about the whole
# import graph. A module's or shared's Docker run includes no migration tests:
# they are one of base's whole-app suites, and test-docker-migrations skips
# when its list is empty. Left out, every test runs, as before.
# The known units are base, shared and every folder under tests/modules/ (the
# trailing slash matches folders only, so __init__.py is left out, and
# Python's __pycache__ is no module). A name not among them is refused before
# anything runs: narrowed to nothing, pytest would fall back to
# pyproject.toml's testpaths and run every test, the with_infra ones included.
UNIT_NAMES := $(sort base shared $(filter-out __pycache__,$(patsubst tests/modules/%/,%,$(wildcard tests/modules/*/))))
ifneq ($(strip $(unit)),)
ifeq ($(filter $(unit),$(UNIT_NAMES)),)
$(error Unknown unit '$(unit)'. Known units: $(UNIT_NAMES))
endif
UNIT_TEST_FOLDER := tests/$(if $(filter base shared,$(unit)),$(unit),modules/$(unit))
PYTEST_PATHS_LIGHT := $(filter $(UNIT_TEST_FOLDER)/%,$(PYTEST_PATHS_LIGHT))
PYTEST_PATHS_APP_INFRA := $(filter $(UNIT_TEST_FOLDER)/%,$(PYTEST_PATHS_APP_INFRA))
PYTEST_PATHS_MIGRATIONS := $(filter $(UNIT_TEST_FOLDER)/%,$(PYTEST_PATHS_MIGRATIONS))
endif
# Stops make, naming the unit, when unit= leaves a run with no test folders:
# a module with only infrastructure tests asked for its light tests, or a
# module's test folder with no tests yet. pytest given no paths would fall back
# to pyproject.toml's testpaths and run every test, the with_infra ones
# included. Called on the first line of each recipe that runs pytest over
# these lists. make expands a recipe just before running it (under -n too), so
# only the run that would get nothing stops. When the list isn't empty the line
# expands to nothing, and make runs nothing for it; without unit= the lists are
# never empty.
require_tests = $(if $(strip $(1)),,$(error Unit '$(unit)' has no tests for this run in $(UNIT_TEST_FOLDER)/))

# Pytest args
PYTEST_ARGS_VERBOSE := -s -vv
PYTEST_ARGS_COV := \
	--cov=src \
	--cov-report=term-missing \
	--cov-report=html
PYTEST_ARGS_COV_DOCKER := \
	--cov=src \
	--cov-report=term-missing

# Safety
.PHONY: pip-audit
pip-audit:
	$(PIP_AUDIT)

# Code quality
.PHONY: slotscheck lint test check check-ci
slotscheck:
	$(SLOTSCHECK) src

lint:
	uv run ruff check --fix
	uv run ruff format
	uv run tombi format
	uv run tombi lint
	uv run deptry
	$(MAKE) slotscheck
	uv run lint-imports
	uv run mypy

test:
	$(call require_tests,$(PYTEST_PATHS_LIGHT))
	uv run pytest -v \
		$(PYTEST_PATHS_LIGHT) \
		$(PYTEST_ARGS_COV)

check: lint test
	uv run coverage html

check-ci:
	uv run ruff check
	uv run ruff format --check
	uv run tombi format --check
	uv run tombi lint
	uv run deptry
	$(MAKE) slotscheck
	uv run lint-imports
	uv run mypy
	$(MAKE) test
	uv run coverage html

# Self-hosted docs wiki (see docs/plans/5-self-hosted-docs-wiki.md)
.PHONY: wiki wiki-build wiki-generate wiki-full
wiki-generate:
	uv run python scripts/wiki/dependency_graph.py
	uv run python scripts/wiki/complexity_report.py

wiki: wiki-generate
	uv run mkdocs serve --dev-addr 127.0.0.1:$(WIKI_PORT)

wiki-build: wiki-generate
	uv run mkdocs build

# One-shot pipeline: full integration tests, then regenerate the
# dependency-graph/complexity pages from current code, build the wiki
# to confirm it's clean, then serve it for review -- avoids running
# test-docker/wiki-generate/wiki-build/wiki as separate one-off commands.
wiki-full: test-docker wiki-generate
	uv run mkdocs build
	uv run mkdocs serve --dev-addr 127.0.0.1:$(WIKI_PORT)

# Docker compose
.PHONY: docker-env local-env upd up upd-local up-local down stop-all open-dashboards cli-up cli ps logs
docker-env:
	$(DOCKER_ENV)

local-env:
	$(LOCAL_ENV)

upd: docker-env
	$(DOCKER_COMPOSE) up -d --build --force-recreate
	if [ "$(ENVIRONMENT)" = "development" ] && [ -n "$(OPEN_DASHBOARD_LIST)" ]; then $(MAKE) open-dashboards; fi

up: docker-env
	$(DOCKER_COMPOSE) up --build --force-recreate

# Opens each dashboard named in OPEN_DASHBOARDS, in its listed order. An
# unknown name is reported, with the valid names, rather than silently
# skipped, so a typo is visible.
open-dashboards:
	@if [ -z "$(OPEN_DASHBOARD_LIST)" ]; then echo "OPEN_DASHBOARDS is empty: no dashboards to open."; exit 0; fi
	@echo "Opening dashboards in browser: $(OPEN_DASHBOARD_LIST)"
	@sleep 2
	@$(foreach d,$(OPEN_DASHBOARD_LIST),$(if $(DASHBOARD_URL_$(d)),xdg-open $(DASHBOARD_URL_$(d)) >/dev/null 2>&1 || true;,echo "Unknown dashboard '$(d)', skipped. Known: $(DASHBOARDS)";)) true

upd-local: local-env
	$(DOCKER_COMPOSE) up -d --build --force-recreate $(INFRA_SERVICES) $(INFRA_INIT_SERVICES)

up-local: local-env
	$(DOCKER_COMPOSE) up --build --force-recreate $(INFRA_SERVICES) $(INFRA_INIT_SERVICES)

down:
	$(DOCKER_COMPOSE) down

# `docker compose ps`/`logs` without `-p $(PROJECT_NAME)` look at the wrong
# Compose project (Docker's own default, derived from the current directory
# name) and silently show nothing when PROJECT_NAME is overridden via
# APP_SERVICE_NAME -- these wrap the same $(DOCKER_COMPOSE) alias every other
# target here already uses, so they always match what `make upd` started.
ps:
	$(DOCKER_COMPOSE) ps

# `service=app` narrows to one container's logs; omitted, shows every
# service's. `-f` follows (Ctrl-C to stop); `tail=N` overrides the default
# scrollback, e.g. `make logs service=app tail=500`.
logs:
	$(DOCKER_COMPOSE) logs -f --tail=$(or $(tail),200) $(strip $(service))

stop-all:
	docker ps -q | xargs -r docker stop

.PHONY: prune
prune:
	$(DOCKER_PRUNE)

# `app.base.main.cli` -- `cli-up` brings the stack up if it isn't already (a
# plain `up --wait`, not `upd`'s `--force-recreate`: idempotent/no-op when
# everything's already healthy, instead of tearing down and rebuilding every
# container) before running the command; `cli` skips that and assumes the
# stack from a prior `make upd`/`cli-up` is still up, for fast repeated
# invocations. Both `exec` (not `run`) into the running `app` container, so
# they share its live DB connection instead of spinning up a fresh one.
cli-up: docker-env
	if [ -z "$(strip $(args))" ]; then \
	  echo 'ERROR: args is required, e.g. make cli-up args="users list"' >&2; \
	  exit 2; \
	fi
	$(DOCKER_COMPOSE) up -d --build --wait
	$(DOCKER_COMPOSE) exec app python -m app.base.main.cli $(args)

cli:
	if [ -z "$(strip $(args))" ]; then \
	  echo 'ERROR: args is required, e.g. make cli args="users list"' >&2; \
	  exit 2; \
	fi
	$(DOCKER_COMPOSE) exec app python -m app.base.main.cli $(args)

# Migrations
.PHONY: migration
migration: local-env
	MIGRATION_DB_SERVICE=$(MIGRATION_DB_SERVICE) \
	INFRA_INIT_SERVICES="$(INFRA_INIT_SERVICES)" \
	STAIRWAY_TEST=$(STAIRWAY_TEST) \
	$(MIGRATION) "$(msg)"

# Tests (with infra)
.PHONY: test-docker test-docker-app test-docker-migrations
test-docker-app: docker-env
	$(call require_tests,$(PYTEST_PATHS_APP_INFRA))
	rc=0; \
	$(DC_TEST_DOCKER) down -v --remove-orphans >/dev/null 2>&1 || true; \
	if [ -n "$(strip $(INFRA_SERVICES))" ]; then \
	  $(DC_TEST_DOCKER) up -d --build --wait --wait-timeout 180 $(INFRA_SERVICES) worker; \
	  if [ -n "$(strip $(INFRA_INIT_SERVICES))" ]; then \
	    $(DC_TEST_DOCKER) up --build $(INFRA_INIT_SERVICES) >/dev/null; \
	  fi; \
	else \
	  echo "INFRA_SERVICES is empty, skipping infra startup"; \
	fi; \
	$(DC_TEST_DOCKER) run -T --build --name $(TEST_RUNNER) app \
		pytest $(PYTEST_ARGS_VERBOSE) \
			$(PYTEST_PATHS_APP_INFRA) \
			$(PYTEST_ARGS_COV_DOCKER) \
		|| rc=$$?; \
	docker cp $(TEST_RUNNER):/tmp/.coverage ./.coverage.docker 2>/dev/null || true; \
	docker rm $(TEST_RUNNER) >/dev/null 2>&1 || true; \
	$(DC_TEST_DOCKER) down -v --remove-orphans; \
	exit $$rc

test-docker-migrations: docker-env
	if [ -z "$(strip $(PYTEST_PATHS_MIGRATIONS))" ] || [ -z "$(strip $(MIGRATION_DB_SERVICE))" ]; then \
	  echo "PYTEST_PATHS_MIGRATIONS or MIGRATION_DB_SERVICE is empty, skipping migrations tests"; \
	  exit 0; \
	fi; \
	rc=0; \
	$(DC_TEST_DOCKER) down -v --remove-orphans >/dev/null 2>&1 || true; \
	$(DC_TEST_DOCKER) up -d --build --wait --wait-timeout 180 $(MIGRATION_DB_SERVICE); \
	$(DC_TEST_DOCKER) run -T --build --no-deps --name $(TEST_RUNNER) app \
		pytest $(PYTEST_ARGS_VERBOSE) \
			$(PYTEST_PATHS_MIGRATIONS) \
		|| rc=$$?; \
	docker rm $(TEST_RUNNER) >/dev/null 2>&1 || true; \
	$(DC_TEST_DOCKER) down -v --remove-orphans; \
	exit $$rc

# One integration test file (or directory) in the same throwaway Docker test
# stack as test-docker-app, for quick RED/GREEN cycles on a test that needs
# real infrastructure, e.g.:
#   make test-docker-file path=tests/modules/organizations/integration/with_infra/test_organization_lists.py
# The app container's `pytest` entrypoint runs the migrations first, exactly
# as in test-docker-app. No coverage report. The full `make test-docker`
# still runs before every commit (agents.md 1.3).
.PHONY: test-docker-file
test-docker-file: docker-env
	if [ -z "$(strip $(path))" ]; then \
	  echo 'ERROR: path is required, e.g. make test-docker-file path=tests/base/integration/with_infra/...' >&2; \
	  exit 2; \
	fi
	rc=0; \
	$(DC_TEST_DOCKER) down -v --remove-orphans >/dev/null 2>&1 || true; \
	if [ -n "$(strip $(INFRA_SERVICES))" ]; then \
	  $(DC_TEST_DOCKER) up -d --build --wait --wait-timeout 180 $(INFRA_SERVICES) worker; \
	  if [ -n "$(strip $(INFRA_INIT_SERVICES))" ]; then \
	    $(DC_TEST_DOCKER) up --build $(INFRA_INIT_SERVICES) >/dev/null; \
	  fi; \
	fi; \
	$(DC_TEST_DOCKER) run -T --build --rm app \
		pytest $(PYTEST_ARGS_VERBOSE) $(path) \
		|| rc=$$?; \
	$(DC_TEST_DOCKER) down -v --remove-orphans; \
	exit $$rc

test-docker:
	$(MAKE) test-docker-app
	$(MAKE) test-docker-migrations
	uv run coverage html --data-file=.coverage.docker -d htmlcov-docker && \
		echo "Coverage HTML report: htmlcov-docker/index.html" || true

# Project structure visualization
.PHONY: pycache-del tree plot-data
pycache-del:
	$(PYCACHE_DEL)

tree: pycache-del
	tree

plot-data:
	APP_LOGGING_LEVEL=CRITICAL uv run python $(DISHKA_PLOT_DATA)
