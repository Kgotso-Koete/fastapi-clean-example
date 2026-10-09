import logging
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands.exceptions import EmailAlreadyExistsError
from app.outbound.adapters.sqla_flusher import SqlaFlusher
from app.outbound.exceptions import StorageError

# SqlaFlusher turns a database uniqueness clash into a domain error (409) and
# any other constraint failure into StorageError (503). Step 3 of
# docs/plans/15-upstream-autumn-2026.md makes sure neither path puts personal
# data in the logs: a SQLAlchemy IntegrityError's text carries the SQL
# statement's parameters (here: an email and a password hash) and Postgres's
# DETAIL line (which repeats the clashing value). OWASP's Logging Cheat Sheet
# says not to log those.

_LOGGER = "app.outbound.adapters.sqla_flusher"

# Stand-ins for the personal data a real failed INSERT INTO users carries.
_EMAIL = "peter.parker@dailybugle.com"
_PASSWORD_HASH = "$2b$11$stand-in-password-hash"


class _FakeDriverError(Exception):
    """What psycopg raises underneath SQLAlchemy: a message (with Postgres's
    DETAIL line) and a `diag` object naming the violated constraint."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(
            f'duplicate key value violates unique constraint "{constraint_name}"\n'
            f"DETAIL:  Key (email)=({_EMAIL}) already exists."
        )
        self.diag = SimpleNamespace(constraint_name=constraint_name)


def _integrity_error(constraint_name: str) -> IntegrityError:
    # Built the way SQLAlchemy builds one: statement, parameters, driver error.
    # Its str() includes all three, which is exactly what must not be logged.
    return IntegrityError(
        statement="INSERT INTO users (email, password_hash) VALUES (%(email)s, %(password_hash)s)",
        params={"email": _EMAIL, "password_hash": _PASSWORD_HASH},
        orig=_FakeDriverError(constraint_name),
    )


class _FailingSession:
    """Stands in for AsyncSession; only flush() is used, and it fails."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def flush(self) -> None:
        raise self._error


def _flusher_failing_with(error: Exception) -> SqlaFlusher:
    return SqlaFlusher(cast(AsyncSession, _FailingSession(error)))


async def test_a_known_uniqueness_clash_raises_the_domain_error_without_the_database_error_attached() -> None:
    flusher = _flusher_failing_with(_integrity_error("uq_users_email"))

    with pytest.raises(EmailAlreadyExistsError) as excinfo:
        await flusher.flush()

    # `raise ... from None`: the IntegrityError (with the email and password
    # hash in its text) is no longer the cause, so nothing that logs causes,
    # like log_info(), can ever print it.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


async def test_an_unrecognised_constraint_clash_logs_only_the_constraint_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    flusher = _flusher_failing_with(_integrity_error("fk_api_keys_user_id"))

    with pytest.raises(StorageError):
        await flusher.flush()

    # The constraint's name is enough to find the cause; the statement's
    # values, and Postgres's DETAIL line repeating them, are never logged.
    logged = [r.getMessage() for r in caplog.records]
    assert logged == ["Unhandled integrity error on constraint: fk_api_keys_user_id"]
    assert not any(_EMAIL in line or _PASSWORD_HASH in line for line in logged)
