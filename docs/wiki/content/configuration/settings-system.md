# Settings System (pydantic-settings)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/config/settings.py`](../../../../src/app/main/config/settings.py) — plain `pydantic.BaseModel` settings groups: field names, defaults, validation
    - [`src/app/main/config/loader.py`](../../../../src/app/main/config/loader.py) — `pydantic_settings.BaseSettings` env-loading classes and the `load_*_settings()` functions that produce the plain models
    - [`src/app/main/run.py`](../../../../src/app/main/run.py) — `make_app()`, which calls every `load_*_settings()` function and wires the results into the DI (Dependency Injection) container
    - `.env` (generated from [`env.example`](../../../../env.example) + `.secrets`; see [Environment Variables](environment-variables.md)) — the actual `KEY=value` source `loader.py` reads from; gitignored, so there is no tracked file to link to directly

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## Two files, two jobs

This codebase deliberately splits "what a setting *is*" from "how a setting gets its value from the environment" into two separate files:

- [`settings.py`](../../../../src/app/main/config/settings.py) defines plain `pydantic.BaseModel` classes — `AppSettings`, `PostgresSettings`, `JwtSettings`, and so on. These carry field names, types, defaults, and validation rules (e.g. `PasswordHasherSettings.PEPPER: str = Field(min_length=32)`), and nothing about environment variables at all. They're what the rest of the app (`make_app()`, DI providers) actually type-hints against.
- [`loader.py`](../../../../src/app/main/config/loader.py) defines a parallel `pydantic_settings.BaseSettings` subclass for each group — `AppEnvConfig`, `PostgresEnvConfig`, `JwtEnvConfig`, etc. — each one multiply-inheriting from `BaseSettings` *and* the matching plain model from `settings.py`, adding only an `env_prefix` (e.g. `APP_`, `JWT_`, `POSTGRES_`). A `load_*_settings()` function instantiates the `EnvConfig` class (which reads and validates real environment variables) and hands back the value typed as the plain `Settings` model.

!!! figure "Settings loading flow, one group at a time"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph src["Source"]
            envfile[(".env")]
        end

        subgraph loader["loader.py"]
            envconfig["JwtEnvConfig(BaseSettings, JwtSettings)<br/>env_prefix='JWT_'"]
        end

        subgraph settingspy["settings.py"]
            plainmodel["JwtSettings(BaseModel)<br/>SECRET, ALGORITHM"]
        end

        subgraph consumer["run.py"]
            makeapp["make_app()"]
            di["DI container context"]
        end

        envfile -->|"JWT_SECRET=...<br/>JWT_ALGORITHM=..."| envconfig
        envconfig -->|"validated instance,<br/>typed as JwtSettings"| plainmodel
        plainmodel --> makeapp
        makeapp --> di

        linkStyle default stroke-width:3px,stroke:#333333
        style src stroke-width:1px,stroke:#333333
        style loader stroke-width:1px,stroke:#333333
        style settingspy stroke-width:1px,stroke:#333333
        style consumer stroke-width:1px,stroke:#333333
    ```

    > Each of the eleven settings groups goes through this same shape independently: `.env` (generated from [`env.example`](../../../../env.example) + `.secrets`, see [Environment Variables](environment-variables.md)) supplies `PREFIX_FIELD=value` lines; the matching `*EnvConfig` class in `loader.py` reads only the keys under its own prefix and validates them against the field types/constraints declared on the `*Settings` model it inherits from; the result is handed to the rest of the app already typed as the plain model, with no `EnvConfig` class ever visible outside `loader.py`.

## Why two files instead of one

Every settings group could, in principle, be a single class combining both the field definitions and the `BaseSettings`/`env_prefix` config. Splitting them keeps `settings.py` reusable outside the "read from environment variables" context — the plain `*Settings` models are exactly what `make_app()`'s keyword arguments accept for overriding settings in tests (see the `app_settings: AppSettings | None = None` pattern in [`run.py`](../../../../src/app/main/run.py)), and what the DI container's `context={...}` mapping is keyed by. A test can construct `JwtSettings(SECRET="test-secret-value-32-chars-long!")` directly, with zero environment variables involved, `BaseSettings` machinery, or `.env` file on disk — only `loader.py`'s `EnvConfig` subclasses actually touch `pydantic_settings`.

!!! figure "Two ways to end up with a JwtSettings instance"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart LR
        subgraph normal["Normal app startup"]
            envread["JwtEnvConfig() reads<br/>JWT_SECRET, JWT_ALGORITHM<br/>from .env"]
        end

        subgraph test["Unit test"]
            construct["JwtSettings(SECRET='...',<br/>ALGORITHM='HS256')<br/>constructed directly"]
        end

        result["JwtSettings instance<br/>passed to make_app()"]

        normal --> result
        test --> result

        linkStyle default stroke-width:3px,stroke:#333333
        style normal stroke-width:1px,stroke:#333333
        style test stroke-width:1px,stroke:#333333
    ```

    > Both paths produce the exact same type — `make_app()`'s type hints and every DI provider only ever see `JwtSettings`, never `JwtEnvConfig`. The right-hand path is what lets unit tests construct a fully-formed app with hand-picked settings and zero filesystem or environment-variable dependency; only the left-hand path touches `pydantic_settings`/`.env` at all.

## The settings groups

`settings.py` currently defines eleven groups, each with its own `env_prefix` in `loader.py`:

| Settings class | Prefix | Notable fields / validation |
|---|---|---|
| `AppSettings` | `APP_` | `SERVICE_NAME`, `LOGGING_LEVEL`, `LOG_FORMAT` (`"human"` \| `"json"`); `ENVIRONMENT` is the one field on this model that reads the **bare** `ENVIRONMENT` variable (`validation_alias="ENVIRONMENT"`, not `APP_ENVIRONMENT`) since it's the same variable `docker-compose.yml`/`Dockerfile`/`scripts/makefile/*.sh` already read — restricted to the `Literal["development", "production"]` type, so an invalid value fails Pydantic validation at startup rather than silently falling through |
| `PostgresSettings` | `POSTGRES_` | `DB`, `HOST`, `PORT`, `USER`, `PASSWORD`; exposes a `dsn` property that builds a `postgresql+psycopg://...` connection string via `PostgresDsn.build()` |
| `SqlaSettings` | `SQLA_` | SQLAlchemy engine tuning: `ECHO`, `ECHO_POOL`, `POOL_SIZE`, `MAX_OVERFLOW` |
| `PasswordHasherSettings` | `PASSWORD_` | `PEPPER` has no default and `Field(min_length=32)` — omitting or under-sizing it fails validation immediately; `WORK_FACTOR`, `MAX_THREADS`, `SEMAPHORE_WAIT_TIMEOUT_S` tune the bcrypt-style hashing work |
| `JwtSettings` | `JWT_` | `SECRET` has no default and `Field(min_length=32)`, same fail-fast pattern as the pepper above; `ALGORITHM` defaults to `HS256` |
| `SessionSettings` | `SESSION_` | `TTL_MIN` (`Field(ge=1)`), `REFRESH_THRESHOLD_RATIO` (`Field(gt=0, lt=1)`); exposes a `ttl` property returning a `timedelta` |
| `CookieSettings` | `COOKIE_` | `NAME`, `PATH`, `HTTPONLY`, `SECURE`, `SAMESITE` (`Literal["lax", "strict", "none"]`) — the auth cookie's actual `Set-Cookie` attributes |
| `EmailSettings` | `EMAIL_` | `USE_CONSOLE` (print instead of sending real SMTP (Simple Mail Transfer Protocol) mail), `SMTP_HOST`/`PORT`/`USERNAME`/`PASSWORD`/`USE_TLS`, `FROM_EMAIL`, `FROM_NAME` |
| `RedisSettings` | `REDIS_` | `HOST`, `PORT`, `DB`, `RESULT_DB` (two separate logical Redis databases on the same instance — broker vs. result backend), `PASSWORD`; exposes `url`/`result_url` properties that build `redis://` connection strings, only including a `:password@` segment when `PASSWORD` is actually set |
| `CelerySettings` | `CELERY_` | `ENABLED` (the master on/off switch — see [Deployment Environments](deployment-environments.md)), `TASK_DEFAULT_QUEUE`, `TASK_ACKS_LATE`, `WORKER_PREFETCH_MULTIPLIER`, `WORKER_CONCURRENCY`, `OUTBOX_RETAIN_AFTER_RELAY`, `DRAIN_OUTBOX_INTERVAL_SECONDS` |
| `AlertSettings` | `ALERT_` | `ENABLED`, `TO_EMAILS`/`CC_EMAILS`/`BCC_EMAILS` (raw comma-separated strings), `COOLDOWN_S`; exposes `to_emails`/`cc_emails`/`bcc_emails` properties that split the raw string into a `list[str]` via the module-level `_split_emails()` helper — a deliberate choice matching this project's flat `KEY=value` env var style instead of requiring JSON (JavaScript Object Notation)-encoded values in an env var |

For the exact variable names each prefix expects, see the [Environment Variables](environment-variables.md) reference, which walks `env.example` group by group.

## Nested settings and validation, concretely

Two patterns recur across every group above and are worth calling out explicitly:

- **Fail-fast required secrets.** `JwtSettings.SECRET` and `PasswordHasherSettings.PEPPER` both have no default value and both carry `Field(min_length=32)`. Because `loader.py`'s `_load_settings()` calls `env_cls()` with no arguments, a missing or too-short value raises a `pydantic.ValidationError` the moment `load_jwt_settings()`/`load_password_hasher_settings()` runs during `make_app()` — the process refuses to start rather than silently running with an empty secret. This is exactly why [`env.example`](../../../../env.example) ships obviously-fake placeholder values (`REPLACE_THIS_WITH_YOUR_OWN_SECRET_JWT_SECRET_VALUE`) for these two instead of a usable default — see the [Environment Variables](environment-variables.md) page's `.secrets` section.
- **Computed properties instead of duplicated logic.** `PostgresSettings.dsn`, `RedisSettings.url`/`result_url`, `SessionSettings.ttl`, and `AlertSettings.to_emails`/`cc_emails`/`bcc_emails` are all `@property` methods on the plain model, not extra env vars. This keeps the *derivation* (building a DSN (Data Source Name) string, splitting a comma-separated list, converting minutes to a `timedelta`) in one place, next to the fields it derives from, rather than scattered across every call site that needs a Postgres connection string or a parsed email list.

## How `loader.py` assembles the final settings object

There isn't a single "final settings object" this codebase assembles once at startup — instead, `run.py`'s `make_app()` calls each `load_*_settings()` function independently (one per group), and passes each result straight into `dishka`'s DI container as a keyed context value (`context={AppSettings: app_settings, PostgresSettings: postgres_settings, ...}`). Any provider elsewhere in the app that needs, say, `JwtSettings` gets it injected by dishka from that same context — nothing re-parses environment variables a second time.

`make_app()` also accepts every settings group as an optional keyword argument (`app_settings: AppSettings | None = None`, etc.) — when a test passes a settings instance directly, `load_*_settings()` for that group is skipped entirely, so a unit test can construct a full app with hand-built settings and never touch `.env` or real environment variables at all.

All eleven `*EnvConfig` classes in [`loader.py`](../../../../src/app/main/config/loader.py) also share one base config, built once as `_DEFAULT_CONFIG_DICT` and merged with each class's own `env_prefix` via `SettingsConfigDict.__or__`:

```python
_DEFAULT_CONFIG_DICT: Final[SettingsConfigDict] = SettingsConfigDict(
    env_file=_ENV_FILE,       # BASE_DIR / ".env"
    env_file_encoding="utf-8",
    extra="ignore",
)
```

`env_file` points at the repo-root `.env` file (`BASE_DIR` is resolved as four parents up from `loader.py`'s own location); `extra="ignore"` means a class only picks up the keys under its own prefix and silently ignores every other line in `.env` — so `JwtEnvConfig` never trips over `POSTGRES_HOST` sitting in the same file.

## Where to go next

- [Environment Variables (.env / .secrets)](environment-variables.md) — the full reference of every variable `env.example` defines, grouped by prefix, and how `.secrets` layers on top of it.
- [Deployment Environments (development vs production)](deployment-environments.md) — how the `ENVIRONMENT` and `CELERY_ENABLED` fields on `AppSettings`/`CelerySettings` drive what actually runs.
- [Getting Started → Quick Start with Docker](../getting-started/quick-start-docker.md) — the one-time `.secrets` setup this settings system depends on.
