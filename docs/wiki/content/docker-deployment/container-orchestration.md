# Container Orchestration & Profiles

!!! sourcefiles "Relevant Source Files/Folders"
    - [`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh) — derives `COMPOSE_PROFILES` from `CELERY_ENABLED`/`ENVIRONMENT`, in full
    - [`docker-compose.yml`](../../../../docker-compose.yml) — every service's `profiles:` list this mechanism gates
    - [`env.example`](../../../../env.example) — where `CELERY_ENABLED`/`ENVIRONMENT` themselves are set
    - [`Makefile`](../../../../Makefile) — the `docker-env` target that runs this script before every `make upd`/`make up`/`make test-docker`

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

[Quick Start with Docker](../getting-started/quick-start-docker.md) already shows *which containers* end up running for a given `CELERY_ENABLED`/`ENVIRONMENT` combination. This page is about the mechanism underneath that — how Compose's `profiles:` feature works in general, and exactly how [`docker_env.sh`](../../../../scripts/makefile/docker_env.sh) turns two plain settings into the `COMPOSE_PROFILES` string Compose actually reads.

## The general rule: profiles are OR-matched, per service

!!! figure "Compose's profile-matching rule (general mechanism, not specific to this repo)"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph rule["Per-service profile check, at 'docker compose up'"]
            noprofile["service has no profiles: key"] --> alwaysrun(["always starts,\nregardless of COMPOSE_PROFILES"])
            svc["service.profiles: [p1, p2, ...]"] --> match{"is ANY of its own profiles\npresent in COMPOSE_PROFILES?"}
            match -->|yes| included(["service starts"])
            match -->|no| excluded(["service skipped"])
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style rule stroke-width:1px,stroke:#333333
    ```

    > A Compose service with no `profiles:` key at all (`app`, `db_pg` in this repo) always starts. A service that *does* declare `profiles:` starts if **any one** of the strings it lists is present in `COMPOSE_PROFILES` — this is an OR across a single service's own profile list, never an AND. There's no way to express "start this service only when both profile A and profile B are active" directly on one service — if a deployment needs that, the only option is to invent a **third, combined profile string** that's computed to be active exactly when both underlying conditions hold, and put every service that needs "A and B" behind that third string instead. That's exactly what `celery-development` is, below.

## How `docker_env.sh` computes it, line by line

!!! figure "docker_env.sh's actual variable names and branches"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        envfile[(".env\n(regenerated from env.example + .secrets)")] --> read1["celery_enabled=$(grep CELERY_ENABLED .env)"]
        envfile --> read2["environment=$(grep ENVIRONMENT .env)"]

        read2 --> validate{"environment ==\n'development' or 'production'?"}
        validate -->|no| err(["exit 1 — hard error"])
        validate -->|yes| initprofiles["profiles=\"\""]
        read1 --> initprofiles

        initprofiles --> checkcelery{"celery_enabled != 'false'?"}
        checkcelery -->|yes| addcelery["profiles+=celery,"]
        checkcelery -->|no| skipcelery["(nothing added)"]

        addcelery --> checkdev{"environment ==\n'development'?"}
        skipcelery --> checkdev
        checkdev -->|yes| adddev["profiles+=development,"]
        checkdev -->|no| skipdev["(nothing added)"]

        adddev --> checkboth{"celery_enabled != 'false'\nAND environment == 'development'?"}
        skipdev --> checkboth
        checkboth -->|yes| addboth["profiles+=celery-development,"]
        checkboth -->|no| skipboth["(nothing added)"]

        addboth --> strip["strip trailing comma"]
        skipboth --> strip
        strip --> append["echo COMPOSE_PROFILES=$profiles >> .env"]

        linkStyle default stroke-width:3px,stroke:#333333
    ```

    > This is the script's actual logic, not a simplification of it:
    >
    > 1. `docker_env.sh` first (re)generates `.env` itself by concatenating [`env.example`](../../../../env.example) then `.secrets` (if present) — so `celery_enabled`/`environment` below are read from that just-generated file, always reflecting the real, current values, not stale ones from a previous run.
    > 2. `celery_enabled=$(grep -E '^CELERY_ENABLED=' .env | tail -1 | cut -d= -f2)` and `environment=$(grep -E '^ENVIRONMENT=' .env | tail -1 | cut -d= -f2)` — `tail -1` matters here: if `.secrets` repeats a key already in `env.example`, the last occurrence in the file wins, exactly matching how `.env` itself is meant to be read.
    > 3. `environment` is validated against exactly `"development"` or `"production"` — anything else, including a typo, is a hard `exit 1` with a message naming the bad value, not a silent fallback to either direction. This is the same guard [`Dockerfile`](../../../../Dockerfile) enforces independently at build time (see [Multi-Stage Docker Build](multi-stage-build.md)) and `AppSettings.ENVIRONMENT`'s `Literal["development", "production"]` type enforces again at application startup.
    > 4. `profiles` starts as an empty string and is built up by three independent, sequential `[ ... ] && profiles="${profiles}<name>,"` checks:
    >    - `celery_enabled != "false"` → append `celery,` (covers `redis`/`worker`, which run in **either** environment as long as Celery itself is on)
    >    - `environment == "development"` → append `development,` (covers `prometheus`/`grafana`/`loki`/`promtail`/`adminer`/`wiki`)
    >    - `celery_enabled != "false"` **and** `environment == "development"` → append `celery-development,` (covers `flower`/`redis-commander` — the AND-condition that has to be computed here specifically because a single service's `profiles:` list can only express OR)
    > 5. `profiles%,` (a bash parameter-expansion trailing-comma strip) removes the final dangling comma, and the result is appended to `.env` as `COMPOSE_PROFILES=...` — appended *last*, deliberately, since `.env` parsing is last-value-wins, so this computed value always overrides anything a stray `COMPOSE_PROFILES=` line in `env.example`/`.secrets` might otherwise set.

`docker_env.sh` also does two more things worth knowing about but out of scope for this page's focus on the profile mechanism itself: it regenerates `.env` from `env.example`/`.secrets` (step 1 above), and it renders the observability stack's `*.template` config files (`observability/prometheus/prometheus.yml.template`, etc.) into real config, substituting in `APP_SERVICE_NAME` via `sed` — see the script's own header comments for that part.

## Where this runs

`docker-env` is a `Makefile` target (`$(DOCKER_ENV)`, i.e. this script) that `upd`, `up`, and `test-docker-app`/`test-docker-migrations` all depend on — `COMPOSE_PROFILES` is always freshly recomputed immediately before Compose is invoked, never left stale from a previous run with different settings.

## Where to go next

- [Getting Started → Quick Start with Docker](../getting-started/quick-start-docker.md) — the concrete "which containers actually start" table and diagram this page's mechanism produces.
- [Docker Containers](docker-containers.md) — every service's exact `profiles:` value, in one reference table.
- [Production Deployment](production-deployment.md) — what `COMPOSE_PROFILES` looks like, concretely, once `ENVIRONMENT=production`.
