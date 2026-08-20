import pytest

from app.main.config.loader import (
    load_alert_settings,
    load_app_settings,
    load_celery_settings,
    load_cookie_settings,
    load_jwt_settings,
    load_password_hasher_settings,
    load_postgres_settings,
    load_redis_settings,
    load_session_settings,
    load_sqla_settings,
)
from app.main.config.logging_ import LoggingLevel


@pytest.mark.parametrize(
    "logging_level",
    [
        LoggingLevel.DEBUG,
        LoggingLevel.INFO,
        LoggingLevel.WARNING,
        LoggingLevel.ERROR,
        LoggingLevel.CRITICAL,
    ],
)
def test_load_app_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch, logging_level: LoggingLevel) -> None:
    monkeypatch.setenv("APP_SERVICE_NAME", "test-service")
    monkeypatch.setenv("APP_VERSION", "test-version")
    monkeypatch.setenv("APP_ROOT_PATH", "test-path")
    monkeypatch.setenv("APP_DEBUG_MODE", "1")
    monkeypatch.setenv("APP_LOGGING_LEVEL", logging_level)

    sut = load_app_settings()

    assert sut.SERVICE_NAME == "test-service"
    assert sut.VERSION == "test-version"
    assert sut.ROOT_PATH == "test-path"
    assert sut.DEBUG_MODE is True
    assert sut.LOGGING_LEVEL == logging_level


def test_load_postgres_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_DB", "test-db")
    monkeypatch.setenv("POSTGRES_HOST", "test-host")
    monkeypatch.setenv("POSTGRES_PORT", "123456789")
    monkeypatch.setenv("POSTGRES_USER", "test-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    sut = load_postgres_settings()

    assert sut.DB == "test-db"
    assert sut.HOST == "test-host"
    assert sut.PORT == 123456789
    assert sut.USER == "test-user"
    assert sut.PASSWORD == "test-password"


def test_load_sqla_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLA_ECHO", "true")
    monkeypatch.setenv("SQLA_ECHO_POOL", "true")
    monkeypatch.setenv("SQLA_POOL_SIZE", "123456789")
    monkeypatch.setenv("SQLA_MAX_OVERFLOW", "987654321")

    sut = load_sqla_settings()

    assert sut.ECHO is True
    assert sut.ECHO_POOL is True
    assert sut.POOL_SIZE == 123456789
    assert sut.MAX_OVERFLOW == 987654321


def test_load_password_hasher_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PASSWORD_PEPPER", "test-pepper-test-pepper-test-pepper")
    monkeypatch.setenv("PASSWORD_WORK_FACTOR", "123456789")
    monkeypatch.setenv("PASSWORD_MAX_THREADS", "987654321")
    monkeypatch.setenv("PASSWORD_SEMAPHORE_WAIT_TIMEOUT_S", "1.23456789")

    sut = load_password_hasher_settings()

    assert sut.PEPPER == "test-pepper-test-pepper-test-pepper"
    assert sut.WORK_FACTOR == 123456789
    assert sut.MAX_THREADS == 987654321
    assert sut.SEMAPHORE_WAIT_TIMEOUT_S == 1.23456789


def test_load_jwt_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-test-secret-test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS384")

    sut = load_jwt_settings()

    assert sut.SECRET == "test-secret-test-secret-test-secret"
    assert sut.ALGORITHM == "HS384"


def test_load_session_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_TTL_MIN", "123465789")
    monkeypatch.setenv("SESSION_REFRESH_THRESHOLD_RATIO", "0.123456789")

    sut = load_session_settings()

    assert sut.TTL_MIN == 123465789
    assert sut.REFRESH_THRESHOLD_RATIO == 0.123456789


def test_load_cookie_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COOKIE_NAME", "test-name")
    monkeypatch.setenv("COOKIE_PATH", "test-path")
    monkeypatch.setenv("COOKIE_HTTPONLY", "1")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("COOKIE_SAMESITE", "strict")

    sut = load_cookie_settings()

    assert sut.NAME == "test-name"
    assert sut.PATH == "test-path"
    assert sut.HTTPONLY is True
    assert sut.SECURE is False
    assert sut.SAMESITE == "strict"


def test_load_alert_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERT_ENABLED", "true")
    monkeypatch.setenv("ALERT_TO_EMAIL", "oncall@example.com")
    monkeypatch.setenv("ALERT_TO_NAME", "Test On-call")
    monkeypatch.setenv("ALERT_COOLDOWN_S", "123.5")

    sut = load_alert_settings()

    assert sut.ENABLED is True
    assert sut.TO_EMAIL == "oncall@example.com"
    assert sut.TO_NAME == "Test On-call"
    assert sut.COOLDOWN_S == 123.5


def test_load_redis_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_HOST", "test-redis-host")
    monkeypatch.setenv("REDIS_PORT", "16379")
    monkeypatch.setenv("REDIS_DB", "2")
    monkeypatch.setenv("REDIS_RESULT_DB", "3")
    monkeypatch.setenv("REDIS_PASSWORD", "test-password")

    sut = load_redis_settings()

    assert sut.HOST == "test-redis-host"
    assert sut.PORT == 16379
    assert sut.DB == 2
    assert sut.RESULT_DB == 3
    assert sut.PASSWORD == "test-password"
    # .url/.result_url build the actual connection strings Celery needs --
    # the broker (DB) and result backend (RESULT_DB) are different Redis
    # logical databases on the same instance, so they get different URLs.
    assert sut.url == "redis://:test-password@test-redis-host:16379/2"
    assert sut.result_url == "redis://:test-password@test-redis-host:16379/3"


def test_load_redis_settings_url_omits_auth_segment_without_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_DB", "0")
    monkeypatch.setenv("REDIS_RESULT_DB", "1")
    monkeypatch.setenv("REDIS_PASSWORD", "")

    sut = load_redis_settings()

    # No ":@" left dangling in the URL when there's no password configured
    # (the common case for local dev, where Redis has no auth at all).
    assert sut.url == "redis://redis:6379/0"
    assert sut.result_url == "redis://redis:6379/1"


def test_load_celery_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_ENABLED", "false")
    monkeypatch.setenv("CELERY_TASK_DEFAULT_QUEUE", "test-queue")
    monkeypatch.setenv("CELERY_TASK_ACKS_LATE", "false")
    monkeypatch.setenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "7")
    monkeypatch.setenv("CELERY_WORKER_CONCURRENCY", "3")

    sut = load_celery_settings()

    assert sut.ENABLED is False
    assert sut.TASK_DEFAULT_QUEUE == "test-queue"
    assert sut.TASK_ACKS_LATE is False
    assert sut.WORKER_CONCURRENCY == 3
    assert sut.WORKER_PREFETCH_MULTIPLIER == 7


def test_load_celery_settings_enabled_defaults_to_true(monkeypatch: pytest.MonkeyPatch) -> None:
    # A deployment that never sets CELERY_ENABLED at all (the common case)
    # should default to Celery being on -- disabling it is an opt-in choice
    # for a Celery-less deployment, not the default.
    monkeypatch.delenv("CELERY_ENABLED", raising=False)

    sut = load_celery_settings()

    assert sut.ENABLED is True
