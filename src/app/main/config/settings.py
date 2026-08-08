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


class EventSettings(BaseModel):
    DISPATCH_MODE: Literal["sync", "background"] = "background"


# vvv ENTIRE CLASS BELOW IS NEW vvv
class AlertSettings(BaseModel):
    """Controls email alerts fired for unhandled (5xx-class) server errors.

    Deliberately separate from EmailSettings: alerts go to operators/devs about
    the *system*, not to end users about their *account*, so they get their own
    toggle, recipient, and rate limit rather than piggybacking on transactional
    email config.
    """

    ENABLED: bool = False
    TO_EMAIL: str = ""
    TO_NAME: str = "On-call"
    # Minimum seconds between two alert emails for the *same* exception type,
    # so an outage that throws thousands of the same error doesn't also flood
    # the inbox. Different exception types are rate-limited independently.
    COOLDOWN_S: float = 300.0
