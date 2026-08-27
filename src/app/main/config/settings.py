from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field, PostgresDsn

from app.main.config.logging_ import LoggingLevel
from app.outbound.auth_ctx.jwt_types import JwtAlgorithm


class AppSettings(BaseModel):
    SERVICE_NAME: str = "clean-example"
    VERSION: str = "development"
    ROOT_PATH: str = "/"
    DEBUG_MODE: bool = False
    LOGGING_LEVEL: LoggingLevel = LoggingLevel.INFO
    LOG_FORMAT: Literal["human", "json"] = "human"  # <-- NEW LINE
    # Bare ENVIRONMENT (no APP_ prefix, unlike every other field here) --
    # the same variable docker-compose.yml/Makefile/Dockerfile already
    # read, via validation_alias rather than AppEnvConfig's env_prefix.
    # "development" reachable Swagger UI (/docs, /redoc); "production"
    # disables both (/openapi.json stays reachable either way -- see
    # setup_docs_url() in run.py).
    ENVIRONMENT: Literal["development", "production"] = Field(default="development", validation_alias="ENVIRONMENT")


class PostgresSettings(BaseModel):
    DB: str
    HOST: str
    PORT: int
    USER: str
    PASSWORD: str

    @property
    def dsn(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.USER,
                password=self.PASSWORD,
                host=self.HOST,
                port=self.PORT,
                path=self.DB,
            ),
        )


class SqlaSettings(BaseModel):
    ECHO: bool = False
    ECHO_POOL: bool = False
    POOL_SIZE: int = 15
    MAX_OVERFLOW: int = 0


class PasswordHasherSettings(BaseModel):
    # https://www.ietf.org/archive/id/draft-ietf-kitten-password-storage-04.html#section-4.2
    PEPPER: str = Field(min_length=32)

    # https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#introduction
    WORK_FACTOR: int = 11
    # CPU-bound & GIL released: per-worker ≈ max(1, floor(effective vCPUs / workers))
    MAX_THREADS: int = 8
    # Fail-fast cap: max semaphore wait before timeout (start ~1 second, tune to peak)
    SEMAPHORE_WAIT_TIMEOUT_S: float = 1.0


class JwtSettings(BaseModel):
    # Min length 32 for 256-bit: https://www.rfc-editor.org/rfc/rfc7518#section-3.2
    SECRET: str = Field(min_length=32)

    ALGORITHM: JwtAlgorithm = "HS256"


class SessionSettings(BaseModel):
    TTL_MIN: int = Field(ge=1, default=5)
    REFRESH_THRESHOLD_RATIO: float = Field(gt=0, lt=1, default=0.2)

    @property
    def ttl(self) -> timedelta:
        return timedelta(minutes=self.TTL_MIN)


class CookieSettings(BaseModel):
    NAME: str = "auth_token"
    PATH: str = "/"
    HTTPONLY: bool = True
    SECURE: bool = False
    SAMESITE: Literal["lax", "strict", "none"] = "lax"


class EmailSettings(BaseModel):
    USE_CONSOLE: bool = True
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    FROM_EMAIL: str = "noreply@example.com"
    FROM_NAME: str = "Clean Example"


class RedisSettings(BaseModel):
    """
    Connection details for the Redis instance used as Celery's message
    broker. DB and RESULT_DB are two different logical databases on the
    *same* Redis instance (Redis supports several, numbered from 0) --
    keeping the broker's queue data and the result backend's task-outcome
    data in separate databases avoids their keys colliding with each other.
    """

    HOST: str = "redis"
    PORT: int = 6379
    DB: int = 0
    RESULT_DB: int = 1
    PASSWORD: str = ""

    @property
    def url(self) -> str:
        """The broker URL Celery connects to for sending/receiving tasks."""
        return self._build_url(self.DB)

    @property
    def result_url(self) -> str:
        """The result backend URL Celery uses to store/query task outcomes."""
        return self._build_url(self.RESULT_DB)

    def _build_url(self, db: int) -> str:
        # Only include a ":password@" segment when a password is actually
        # set -- otherwise the URL would have a dangling ":@" in it, which
        # is invalid.
        auth = f":{self.PASSWORD}@" if self.PASSWORD else ""
        return f"redis://{auth}{self.HOST}:{self.PORT}/{db}"


class CelerySettings(BaseModel):
    # When False, HybridEventDispatcher runs every handler inline
    # regardless of its own DISPATCH_MODE, instead of publishing
    # "background" handlers to Celery -- lets a deployment skip standing
    # up Redis/a worker entirely (e.g. to save cost) and still reliably
    # run every handler, just without the "don't block the response"
    # benefit for the ones declared "background".
    ENABLED: bool = True
    TASK_DEFAULT_QUEUE: str = "events"
    # acks_late=True: a task is only removed from the queue after it
    # finishes, not the moment a worker picks it up -- so a worker crash
    # mid-task leaves the task to be retried, instead of silently lost.
    TASK_ACKS_LATE: bool = True
    WORKER_PREFETCH_MULTIPLIER: int = 1
    # Celery's own default is one process per CPU core, which competes
    # directly with everything else on the host (Postgres, Redis, the app
    # itself) for the same cores. 2 is a deliberately modest default for
    # this template's expected scale -- raise it if your workload and host
    # actually justify more.
    WORKER_CONCURRENCY: int = 2
    # Defaults to retain (not delete) a relayed row -- see
    # docs/plans/4-transactional-outbox.md, Confirmed Decision #2. Deleting
    # the instant a row is relayed would make the outbox invisible again,
    # defeating the point of making it queryable via Adminer in the first
    # place. drain_outbox always marks a relayed row processed regardless
    # of this setting; it only additionally deletes when this is False.
    OUTBOX_RETAIN_AFTER_RELAY: bool = True
    # How often the worker process's own outbox drain loop ticks -- see
    # app.main.worker.outbox_drain_loop. 3 seconds is a deliberately short
    # default so a background handler's effect (e.g. the welcome email)
    # shows up quickly in local dev; raise it for a deployment where that
    # latency doesn't matter and re-scanning the table that often is
    # wasted work.
    DRAIN_OUTBOX_INTERVAL_SECONDS: float = 3.0


def _split_emails(value: str) -> list[str]:
    """Comma-separated env var -> a clean list, matching this project's flat
    KEY=value env var style (no JSON-in-env-var needed for a list field)."""
    return [email.strip() for email in value.split(",") if email.strip()]


# vvv ENTIRE CLASS BELOW IS NEW vvv
class AlertSettings(BaseModel):
    """Controls email alerts fired for unhandled (5xx-class) server errors.

    Deliberately separate from EmailSettings: alerts go to operators/devs about
    the *system*, not to end users about their *account*, so they get their own
    toggle, recipients, and rate limit rather than piggybacking on transactional
    email config.
    """

    ENABLED: bool = False
    # Comma-separated; use the to_emails/cc_emails/bcc_emails properties below
    # rather than these raw fields directly.
    TO_EMAILS: str = ""
    CC_EMAILS: str = ""
    BCC_EMAILS: str = ""
    # Minimum seconds between two alert emails for the *same* exception type,
    # so an outage that throws thousands of the same error doesn't also flood
    # the inbox. Different exception types are rate-limited independently.
    COOLDOWN_S: float = 300.0

    @property
    def to_emails(self) -> list[str]:
        return _split_emails(self.TO_EMAILS)

    @property
    def cc_emails(self) -> list[str]:
        return _split_emails(self.CC_EMAILS)

    @property
    def bcc_emails(self) -> list[str]:
        return _split_emails(self.BCC_EMAILS)
