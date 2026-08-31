# Docker Containers

!!! sourcefiles "Relevant Source Files/Folders"
    - [`docker-compose.yml`](../../../../docker-compose.yml) — every service this stack can start, its image/build, ports, profiles, and `depends_on`
    - [`Dockerfile`](../../../../Dockerfile) — the one image `app`/`worker`/`wiki` all build from
    - [`env.example`](../../../../env.example) — every `${VAR:-default}` port/credential referenced below
    - [`docker-entrypoint.sh`](../../../../docker-entrypoint.sh) — what `app`/`worker` actually run as their container command

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

The [Overview's container topology diagram](../../index.md#what-actually-runs) already shows *which* containers run together and their `depends_on` edges, grouped by whether Celery/dev tooling is active. This page goes one level deeper: a full per-service reference table, plus two diagrams that slice the same twelve services along axes the Overview diagram doesn't — which ones are built from this repo's own `Dockerfile` versus pulled as off-the-shelf images, and exactly which literal Compose profile string gates each one.

## Built here vs. pulled off the shelf

!!! figure "Which services build from this repo's Dockerfile vs. pull a pre-built image"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph built["Built from this repo's Dockerfile"]
            app["app"]
            worker["worker"]
            wiki["wiki"]
        end

        subgraph pulled["Pulled pre-built images"]
            db_pg[("db_pg")]
            redis[("redis")]
            flower["flower"]
            rediscommander["redis-commander"]
            prometheus["prometheus"]
            grafana["grafana"]
            loki[("loki")]
            promtail["promtail"]
            adminer["adminer"]
        end

        app --> db_pg
        worker --> db_pg
        worker --> redis
        flower --> redis
        rediscommander --> redis
        grafana --> prometheus
        grafana --> loki
        promtail --> loki
        adminer --> db_pg
        prometheus --> app

        linkStyle default stroke-width:3px,stroke:#333333
        style built fill:#b3b3b3,stroke-width:1px,stroke:#333333
        style pulled stroke-width:1px,stroke:#333333
    ```

    > Only three services build an image at all — `app`, `worker`, and `wiki` all compile the *same* [`Dockerfile`](../../../../Dockerfile) (see [Multi-Stage Docker Build](multi-stage-build.md) for what that build actually does), just with different `command:`s at runtime. Every other service pulls a versioned, off-the-shelf image straight from a registry — nothing about this project's own source code is baked into `db_pg`, `redis`, `flower`, `redis-commander`, `prometheus`, `grafana`, `loki`, `promtail`, or `adminer`. The arrows are the same real `depends_on` relationships already shown in the Overview.

## Which Compose profile gates each service

!!! figure "Literal COMPOSE_PROFILES strings, mapped to the services they gate"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph profiles["Compose profiles"]
            none["(no profiles: key — always on)"]
            celery["celery"]
            celerydev["celery-development"]
            development["development"]
        end

        none --> app2["app"]
        none --> db_pg2["db_pg"]
        celery --> redis2["redis"]
        celery --> worker2["worker"]
        celerydev --> flower2["flower"]
        celerydev --> rediscommander2["redis-commander"]
        development --> prometheus2["prometheus"]
        development --> grafana2["grafana"]
        development --> loki2["loki"]
        development --> promtail2["promtail"]
        development --> adminer2["adminer"]
        development --> wiki2["wiki"]

        linkStyle default stroke-width:3px,stroke:#333333
        style profiles stroke-width:1px,stroke:#333333
    ```

    > `app` and `db_pg` have no `profiles:` key at all in `docker-compose.yml`, so they start unconditionally. Every other service declares exactly one profile string, and starts only when that string appears in `COMPOSE_PROFILES` — see [Container Orchestration & Profiles](container-orchestration.md) for exactly how `COMPOSE_PROFILES` itself gets computed from `ENVIRONMENT`/`CELERY_ENABLED`.

## Full service reference

| Service | Image / Build | Purpose | Host port | Profile | `depends_on` |
|---|---|---|---|---|---|
| `app` | build: [`Dockerfile`](../../../../Dockerfile) | FastAPI application server (`uvicorn`, via `docker-entrypoint.sh start`) | `127.0.0.1:${UVICORN_PORT:-8000}:8000` | *(none — always on)* | `db_pg` (healthy) |
| `db_pg` | `postgres:18-alpine` | Primary Postgres database | `127.0.0.1:${POSTGRES_PORT:-5432}:5432` | *(none — always on)* | — |
| `redis` | `redis:8-alpine` | Celery broker + result backend | `127.0.0.1:${REDIS_PORT:-6379}:6379` | `celery` | — |
| `worker` | build: [`Dockerfile`](../../../../Dockerfile) (same image as `app`) | Celery worker: runs `"background"`-mode event handlers and drains the transactional outbox (`docker-entrypoint.sh worker`) | *(not exposed)* | `celery` | `db_pg` (healthy), `redis` (healthy) |
| `flower` | `mher/flower:2.0` | Celery task monitoring dashboard | `127.0.0.1:${FLOWER_PORT:-5555}:5555` | `celery-development` | `redis` (healthy) |
| `redis-commander` | `rediscommander/redis-commander:latest` | Browse Redis's actual broker/result-backend contents | `127.0.0.1:${REDIS_COMMANDER_PORT:-8081}:8081` | `celery-development` | `redis` (healthy) |
| `prometheus` | `prom/prometheus:v3.13.2` | Scrapes `app`'s `/metrics` endpoint | `127.0.0.1:${PROMETHEUS_PORT:-9090}:9090` | `development` | `app` (started) |
| `grafana` | `grafana/grafana:11.3.4` | Dashboards over Prometheus metrics + Loki logs | `127.0.0.1:${GRAFANA_PORT:-3000}:3000` | `development` | `prometheus`, `loki` (started) |
| `loki` | `grafana/loki:3.7.0` | Log aggregation backend | `127.0.0.1:${LOKI_PORT:-3100}:3100` | `development` | — |
| `promtail` | `grafana/promtail:3.6.8` | Ships every container's logs (via the Docker socket) into `loki` | *(not exposed)* | `development` | `loki` (started) |
| `wiki` | build: [`Dockerfile`](../../../../Dockerfile) (same image as `app`/`worker`) | Serves this documentation wiki (`mkdocs serve`, live-reload) | `127.0.0.1:${WIKI_PORT:-8001}:8000` | `development` | — |
| `adminer` | `adminer:4.8.1` | Web UI (User Interface) for browsing Postgres | `127.0.0.1:${ADMINER_PORT:-8080}:8080` | `development` | `db_pg` (started) |

> A few details the table alone doesn't make obvious:
>
> - **"(healthy)" vs. "(started)" is a real distinction, not just phrasing.** `db_pg`, `redis`, and `worker` each carry a `healthcheck:` block, and anything that names them under `condition: service_healthy` (`app` → `db_pg`; `worker` → `db_pg`, `redis`; `flower`/`redis-commander` → `redis`) genuinely blocks until that healthcheck passes. Every other `depends_on` entry above (`prometheus` → `app`, `grafana` → `prometheus`/`loki`, `promtail` → `loki`, `adminer` → `db_pg`) uses Compose's plain list form, which only waits for the container process to start — not for the service inside it to actually be ready.
> - **Only `app`, `db_pg`, and `worker` have any port bound by default that this stack's own tests or health probes rely on** — every other port in the table exists purely so a human can open it in a browser; nothing in the compose file itself talks to `flower`, `grafana`, etc. over their host port.
> - Every port and image tag above is read straight from `docker-compose.yml`/`env.example` as of this writing — a fork can safely bump image tags (e.g. a newer Postgres major) independently per service, since none of them share a build.
> - `prometheus_data`, `grafana_data`, and `loki_data` are named Docker volumes (declared at the bottom of `docker-compose.yml`) — each dev-only observability service persists its own data across `make down`/`make upd` cycles rather than starting fresh every time.

## Where to go next

- [Multi-Stage Docker Build](multi-stage-build.md) — what the `Dockerfile` these three built services share actually does, stage by stage.
- [Container Orchestration & Profiles](container-orchestration.md) — how `COMPOSE_PROFILES` gets computed, and the general Compose profile-matching rule this page's second diagram is built on.
- [Production Deployment](production-deployment.md) — which of the services above never run at all once `ENVIRONMENT=production`.
