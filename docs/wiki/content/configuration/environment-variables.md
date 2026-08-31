# Environment Variables (.env / .secrets)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`env.example`](../../../../env.example) — every environment variable this project defines, documented inline, committed to the repo
    - `.secrets` — real secret values, layered on top of `env.example`; gitignored, so there is no tracked file to link to
    - [`scripts/makefile/docker_env.sh`](../../../../scripts/makefile/docker_env.sh) — generates `.env` by concatenating `env.example` then `.secrets`
    - [`src/app/main/config/loader.py`](../../../../src/app/main/config/loader.py) — reads the generated `.env` into typed settings objects (see [Settings System](settings-system.md))

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## From two source files to one settings object

Every variable this project reads at runtime traces back to exactly one of two files: the committed [`env.example`](../../../../env.example) (every variable, with a usable default for everything except two deliberately-blank secrets), and the gitignored `.secrets` (real secret values, and any per-deployment override). Neither file is read directly by the app — a generation step concatenates them into `.env`, which `pydantic-settings` then reads (see [Settings System](settings-system.md) for what happens after that point).

!!! figure "From env.example + .secrets to a typed settings object"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        example["env.example<br/>(committed, every KEY=value,<br/>placeholder secrets)"]
        secrets[".secrets<br/>(gitignored, real JWT_SECRET<br/>+ PASSWORD_PEPPER, overrides)"]

        subgraph gen["scripts/makefile/docker_env.sh"]
            concat["cat env.example<br/>then cat .secrets"]
            profiles["derive COMPOSE_PROFILES<br/>from CELERY_ENABLED + ENVIRONMENT"]
        end

        envfile[(".env generated, gitignored")]

        subgraph pyd["loader.py"]
            envconfigs["11x *EnvConfig(BaseSettings)<br/>one env_prefix each"]
        end

        settingsobjs["11x plain *Settings objects, typed"]

        example --> concat
        secrets -->|"appended last,<br/>wins on repeated keys"| concat
        concat --> profiles
        profiles --> envfile
        envfile --> envconfigs
        envconfigs --> settingsobjs

        linkStyle default stroke-width:3px,stroke:#333333
        style gen stroke-width:1px,stroke:#333333
        style pyd stroke-width:1px,stroke:#333333
    ```

    > `docker_env.sh` writes `.env` by running `cat env.example` then, if `.secrets` exists, `cat .secrets` right after it, with a header comment warning not to edit `.env` directly. Because `.env` parsing is last-value-wins, any key `.secrets` repeats from `env.example` overrides it — this is precisely how `JWT_SECRET`/`PASSWORD_PEPPER` go from unusable placeholders to real values without ever touching the committed file. The same script then appends a computed `COMPOSE_PROFILES` line (see [Deployment Environments](deployment-environments.md)), and only after all of that does `loader.py`'s `pydantic-settings` classes read the result.

## The `.secrets` pattern

As covered in [Getting Started → Quick Start with Docker](../getting-started/quick-start-docker.md#one-time-setup-secrets), two settings are deliberately shipped with no usable default in `env.example`: `JWT_SECRET` and `PASSWORD_PEPPER`. Both carry an obvious, committed `REPLACE_THIS_WITH_YOUR_OWN_SECRET_..._VALUE` placeholder — long enough to satisfy `pydantic`'s own `Field(min_length=32)` check on both fields (so validation alone won't catch a deployment that forgets to replace it), but plainly not a real secret, since it's sitting in a committed, public template file. In practice you generate a real value for each with:

```shell
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

and put both into a `.secrets` file (flat `KEY=value`, same format as `env.example`) at the repo root. `.secrets` is gitignored — nothing generated from it, and no value inside it, ever reaches the commit history. Beyond the two secrets above, `.secrets` is also the correct place to override *any* other `env.example` value for a specific deployment or fork (a custom `APP_SERVICE_NAME`, a different `POSTGRES_PASSWORD`, a real SMTP (Simple Mail Transfer Protocol) credential) rather than editing the committed template directly — `env.example`'s own header comments call this out per-variable where it matters (e.g. `POSTGRES_HOST`/`REDIS_HOST`, see the table below).

!!! figure "How env.example's variable groups relate to where a value should actually live"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph mustoverride["Must be overridden in .secrets"]
            jwtpw["JWT_SECRET<br/>PASSWORD_PEPPER"]
        end

        subgraph hostgotcha["Docker-vs-local gotcha — never duplicate in .secrets"]
            hosts["POSTGRES_HOST<br/>REDIS_HOST"]
        end

        subgraph shouldoverride["Usable default, override per deployment"]
            perdeploy["APP_SERVICE_NAME<br/>POSTGRES_PASSWORD<br/>EMAIL_SMTP_*<br/>ALERT_TO_EMAILS"]
        end

        subgraph fineasis["Usable default, rarely needs changing"]
            asis["CELERY_*<br/>observability *_PORT<br/>WIKI_PORT"]
        end

        linkStyle default stroke-width:3px,stroke:#333333
        style mustoverride stroke-width:1px,stroke:#333333
        style hostgotcha stroke-width:1px,stroke:#333333
        style shouldoverride stroke-width:1px,stroke:#333333
        style fineasis stroke-width:1px,stroke:#333333
    ```

    > Four categories, not one flat list: the two secrets that *must* change before any real deployment (validation only checks length, not that they're actually secret — see below); the two Docker-internal hostnames that must **not** be duplicated in `.secrets` at all, since `make upd-local` depends on rewriting its own copy of them; values worth overriding per fork/deployment even though the shipped default technically works; and the remaining majority, which are fine to leave as-is for local development. The full table below tags every variable's group; this diagram is about *how* to treat a value, the table is about *what* it does.

## Variable reference

Every variable currently defined in [`env.example`](../../../../env.example), grouped exactly as the file itself groups them.

### Example

| Variable | Default | What it does |
|---|---|---|
| `EXAMPLE_SERVICE_URL` | `http://example_service:51888` | A placeholder demonstrating the `KEY=value` format; not read by any real settings group. |

### Environment

| Variable | Default | What it does |
|---|---|---|
| `ENVIRONMENT` | `development` | Bare variable, no prefix — read directly by `docker-compose.yml`/`Dockerfile`/`scripts/makefile/*.sh` *and* by `AppSettings.ENVIRONMENT` via `validation_alias`. Must be exactly `development` or `production`; both the shell scripts and the `Dockerfile` hard-fail on anything else. Drives dev-only tooling, dependency install group, and `/docs`/`/redoc` availability — see [Deployment Environments](deployment-environments.md). |

### Service name

| Variable | Default | What it does |
|---|---|---|
| `APP_SERVICE_NAME` | `fastapi-clean-example` | Used for the Compose project name (and therefore every container name), the FastAPI app title, the `/metrics` service-name label, the Celery app name, and Promtail's own-project log filter. A fork should override this in `.secrets`, not edit the template value directly. |

### Uvicorn

| Variable | Default | What it does |
|---|---|---|
| `UVICORN_PORT` | `8000` | Host-side port `docker-compose.yml` maps to the `app` container's internal port 8000. |

### App

| Variable | Default | What it does |
|---|---|---|
| `APP_LOGGING_LEVEL` | `DEBUG` | Python logging level passed to `setup_logging()`. |
| `APP_LOG_FORMAT` | `json` | `"human"` for readable local dev output, `"json"` for structured logs a shipper (Promtail) can parse and filter on. |

### Alerting

| Variable | Default | What it does |
|---|---|---|
| `ALERT_ENABLED` | `false` | Master switch for emailing an on-call address on genuine unhandled (5xx-class) server errors — never ordinary 4xx validation/business errors. |
| `ALERT_TO_EMAILS` | *(empty)* | Comma-separated recipient list, e.g. `oncall@yourdomain.com,backup@yourdomain.com`. |
| `ALERT_CC_EMAILS` | *(empty)* | Comma-separated CC (carbon copy) list. |
| `ALERT_BCC_EMAILS` | *(empty)* | Comma-separated BCC (blind carbon copy) list. |
| `ALERT_COOLDOWN_S` | `300` | Minimum seconds between two alert emails for the *same* exception type, so a flood of identical errors doesn't flood the inbox; different exception types are rate-limited independently. Alerts are actually sent through the `EMAIL_*` settings below. |

### Jwt

| Variable | Default | What it does |
|---|---|---|
| `JWT_SECRET` | *(unusable placeholder)* | Signing secret for session JWTs; `Field(min_length=32)`. Must be replaced with a real generated value in `.secrets` — see the `.secrets` pattern above. |

### Password

| Variable | Default | What it does |
|---|---|---|
| `PASSWORD_PEPPER` | *(unusable placeholder)* | Server-side pepper mixed into password hashing; `Field(min_length=32)`. Same "must replace in `.secrets`" rule as `JWT_SECRET`. |

### Postgres

| Variable | Default | What it does |
|---|---|---|
| `POSTGRES_DB` | `clean-example` | Database name. |
| `POSTGRES_HOST` | `db_pg` | Docker-internal service name. **Do not** also set this in `.secrets` — `make upd-local` (`scripts/makefile/local_env.sh`) rewrites its own copy to `127.0.0.1` since the app then runs on the host, and a `.secrets` entry (appended after that rewrite) silently wins and breaks that path. |
| `POSTGRES_PORT` | `5432` | Host-mapped Postgres port. |
| `POSTGRES_USER` | `postgres` | Postgres role. |
| `POSTGRES_PASSWORD` | `password` | Postgres role password. |

### Email

| Variable | Default | What it does |
|---|---|---|
| `EMAIL_USE_CONSOLE` | `true` | Print emails to console instead of sending real SMTP mail — the local-dev default. |
| `EMAIL_SMTP_HOST` | `smtp-relay.brevo.com` | Any SMTP provider works (Brevo, Mailgun, SES, etc.); this is just the example default. |
| `EMAIL_SMTP_PORT` | `587` | SMTP port. |
| `EMAIL_SMTP_USERNAME` | *(empty)* | SMTP auth username. |
| `EMAIL_SMTP_PASSWORD` | *(empty)* | SMTP auth password — belongs in `.secrets` for a real deployment. |
| `EMAIL_SMTP_USE_TLS` | `true` | Whether to use TLS (Transport Layer Security) for the SMTP connection. |
| `EMAIL_FROM_EMAIL` | `noreply@yourdomain.com` | `From:` address for outgoing mail. |
| `EMAIL_FROM_NAME` | `Your Company Name` | `From:` display name. |

### Redis

| Variable | Default | What it does |
|---|---|---|
| `REDIS_HOST` | `redis` | Same Docker-vs-local gotcha as `POSTGRES_HOST` above — don't duplicate in `.secrets`. |
| `REDIS_PORT` | `6379` | Redis port. |
| `REDIS_DB` | `0` | Logical DB used as the Celery broker. |
| `REDIS_RESULT_DB` | `1` | Separate logical DB used as the Celery result backend, so broker and result keys never collide. |
| `REDIS_PASSWORD` | *(empty)* | Empty matches a local Redis with no auth. |

### Celery

| Variable | Default | What it does |
|---|---|---|
| `CELERY_ENABLED` | `true` | The one setting deciding whether this deployment uses Celery at all. `false` runs every event handler inline regardless of its own `DISPATCH_MODE`, and also removes the `celery` Compose profile entirely — see [Deployment Environments](deployment-environments.md). |
| `CELERY_TASK_DEFAULT_QUEUE` | `events` | Default Celery queue name. |
| `CELERY_TASK_ACKS_LATE` | `true` | A task is only removed from the queue after it finishes, not the moment a worker picks it up — a worker crash mid-task leaves it to be retried instead of silently lost. |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | Celery worker prefetch tuning. |
| `CELERY_WORKER_CONCURRENCY` | `2` | Deliberately modest default (Celery's own default is one process per CPU (Central Processing Unit) core, competing with Postgres/Redis/the app itself for the same cores). |
| `CELERY_OUTBOX_RETAIN_AFTER_RELAY` | `true` | Retain (not delete) an outbox row once relayed, so it stays queryable via Adminer; set `false` to have `drain_outbox` delete it instead. |
| `CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS` | `3` | How often the worker's own outbox drain loop ticks. |

### Flower

| Variable | Default | What it does |
|---|---|---|
| `FLOWER_PORT` | `5555` | Host-mapped port for the Celery task monitoring dashboard (dev-only). |

### Redis Commander

| Variable | Default | What it does |
|---|---|---|
| `REDIS_COMMANDER_PORT` | `8081` | Host-mapped port for browsing the actual Redis broker/result-backend keys (dev-only). |

### Observability stack

| Variable | Default | What it does |
|---|---|---|
| `PROMETHEUS_PORT` | `9090` | Prometheus UI (User Interface) port (dev-only). |
| `GRAFANA_PORT` | `3000` | Grafana UI port (dev-only). |
| `LOKI_PORT` | `3100` | Loki API (Application Programming Interface) port (dev-only). |
| `ADMINER_PORT` | `8080` | Adminer (Postgres UI) port (dev-only). |

### Self-hosted docs wiki

| Variable | Default | What it does |
|---|---|---|
| `WIKI_PORT` | `8001` | Host-mapped port for this wiki's own `mkdocs serve` container (dev-only). |

## Where to go next

- [Settings System (pydantic-settings)](settings-system.md) — what `loader.py` actually does with each of these variables once `.env` exists, and the plain settings models they populate.
- [Deployment Environments (development vs production)](deployment-environments.md) — how `ENVIRONMENT` and `CELERY_ENABLED` specifically drive what starts and what's built.
- [Getting Started → Quick Start with Docker](../getting-started/quick-start-docker.md) — the one-time `.secrets` setup and `make upd` walkthrough this page assumes.
