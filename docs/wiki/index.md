# Overview

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/run.py`](../../src/app/main/run.py) — the entry point; `make_app()` is what `uvicorn` actually runs
    - [`src/app/core/`](../../src/app/core/) — business rules (innermost layer)
    - [`src/app/outbound/`](../../src/app/outbound/) — infrastructure adapters
    - [`src/app/inbound/`](../../src/app/inbound/) — HTTP adapters
    - [`src/app/main/`](../../src/app/main/) — composition root (outermost layer)

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this is

`fastapi-clean-example` is a reference implementation of **Domain-Driven Design**, **Clean Architecture**, and **Test-Driven Development**, built on FastAPI. It exists to be studied and forked, not just run — every non-trivial decision in the codebase is written down as an implementation plan under [`docs/plans/`](https://github.com/ivan-borovets/fastapi-clean-example/tree/master/docs/plans) (these are gradually moving into this wiki over time), and this wiki exists to make that knowledge navigable rather than scattered across flat markdown files.

It also serves a second purpose beyond documenting the architecture itself: the account/user functionality already built here is a worked example of managing real complexity through well-modeled use cases — see **Use Case Examples** for how each one is put together, and as a template for extending this codebase with your own.

## What "Clean Architecture" means here, concretely

!!! figure "Layer boundaries and import direction"
    ![Four concentric layers: main (outermost), inbound, outbound, core (innermost) — imports only ever point inward](images/clean-architecture-layers.svg)

One rule, enforced by a real, passing/failing CI check (`import-linter`), not just convention: an import can only point from an outer layer toward an inner one, never back. `core` — the innermost ring — never knows it's running behind HTTP, or that its data lives in Postgres.

See [Architecture → Layer Dependencies & Import Rules](content/architecture/layer-dependencies.md) for the full explanation, including what the linter does and doesn't actually catch.

## What's actually implemented

Everything below is real, working code in this repository today — not a roadmap.

| Capability | What it does |
|---|---|
| User accounts & RBAC | Sign-up, login/logout, password management, admin grant/revoke, `user`/`admin` roles |
| Cookie + JWT session auth | `HttpOnly` cookie referencing a server-side, revocable session record — not a long-lived stateless bearer token |
| Domain events | Entities record events (`UserRegisteredEvent`, etc.); handlers declare `"sync"` or `"background"` dispatch independently, per handler |
| Transactional outbox | Background-dispatched events are written to the database in the *same transaction* as the state change that triggered them, closing the "dual write" gap between committing to Postgres and publishing to a broker |
| Celery + Redis background jobs | A separate `worker` process drains the outbox and runs background handlers, with a `CELERY_ENABLED=false` inline fallback for deployments that don't want the extra infrastructure |
| Observability | Structured JSON logging, Prometheus metrics, Grafana dashboards, Loki/Promtail log aggregation, and rate-limited email alerting on unhandled 5xx errors |
| Environment-aware deployment gating | A strictly-validated `ENVIRONMENT` setting (`development`/`production`) that gates every piece of dev-only tooling — dashboards, Adminer, Swagger UI — out of production entirely |
| Full test pyramid | Unit tests (fast, no infrastructure), integration tests (real Postgres/Redis via Docker), and smoke tests (a real, separately-running worker container) |

## What actually runs

!!! figure "Container topology"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph always["Always running"]
            app["app"]
            db_pg[("db_pg")]
        end

        subgraph celery["Background jobs"]
            redis[("redis")]
            worker["worker"]
        end

        subgraph celerydev["Celery UIs (dev-only)"]
            flower["flower"]
            rediscommander["redis-commander"]
        end

        subgraph dev["Observability + Admin (dev-only)"]
            prometheus["prometheus"]
            grafana["grafana"]
            loki["loki"]
            promtail["promtail"]
            adminer["adminer"]
        end

        app --> db_pg
        worker --> db_pg
        worker --> redis
        flower --> redis
        rediscommander --> redis
        prometheus --> app
        grafana --> prometheus
        grafana --> loki
        promtail --> loki
        adminer --> db_pg

        linkStyle default stroke-width:3px,stroke:#333333
        style always fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style celery stroke-width:1px,stroke:#333333
        style celerydev stroke-width:1px,stroke:#333333
        style dev stroke-width:1px,stroke:#333333
    ```

`app` and `db_pg` always run. Every arrow is a real `depends_on` from `docker-compose.yml` — the container it points to must be healthy before the one behind the arrow starts. "Background jobs" needs `CELERY_ENABLED=true`; both dev-only groups additionally need `ENVIRONMENT=development` — neither runs on a production deployment. See [Docker and Deployment → Docker Containers](content/docker-deployment/docker-containers.md) for what each one does.

## Where to go next

- **New to the codebase?** Start with [Getting Started](content/getting-started/quick-start-docker.md), then [Architecture](content/architecture/layer-dependencies.md) to understand the layering before reading any single file.
- **Want to understand a specific mechanism?** [Core Patterns](content/core-patterns/ports-and-adapters.md) covers ports/adapters, dependency injection, transaction management, and the domain-events/outbox system individually.
- **Adding something new?** [Use Case Examples](content/use-case-examples/adding-a-use-case.md) walks through every existing account/user use case, plus generic "how to add a new one" guides.
- **Deploying this somewhere real?** See [Configuration](content/configuration/settings-system.md) for environment variables and deployment modes, and [Docker and Deployment](content/docker-deployment/docker-containers.md) for the container topology and production build.
- **Curious what's still missing for production?** The Roadmap page (coming soon) tracks that separately.

## Acknowledgements

This project was created by [Ivan Borovets](https://github.com/ivan-borovets), whose [`fastapi-clean-example`](https://github.com/ivan-borovets/fastapi-clean-example) is the origin of everything documented in this wiki. See the [original README's Acknowledgements section](https://github.com/ivan-borovets/fastapi-clean-example/tree/legacy-2025?tab=readme-ov-file#acknowledgements) for the full list of people and projects that shaped it.

This codebase is **open source, licensed under the MIT License** — free to study, fork, and use, including commercially, with attribution.
