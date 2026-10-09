import logging
from collections.abc import Mapping
from typing import Final

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands.exceptions import (
    EmailAlreadyExistsError,
    PhoneNumberAlreadyExistsError,
    UsernameAlreadyExistsError,
)
from app.core.commands.ports.flusher import Flusher
from app.outbound.exceptions import StorageError
from app.outbound.persistence_sqla import constraint_names as cn

logger = logging.getLogger(__name__)

DB_CONSTRAINT_VIOLATION: Final[str] = "Database constraint violation."
DB_FLUSH_DONE: Final[str] = "Flush was done."
DB_FLUSH_FAILED: Final[str] = "Flush failed."

CONSTRAINT_TO_ERROR: Final[Mapping[str, type[Exception]]] = {
    cn.UQ_USERS_USERNAME: UsernameAlreadyExistsError,
    cn.UQ_USERS_EMAIL: EmailAlreadyExistsError,
    cn.UQ_USERS_PHONE_NUMBER: PhoneNumberAlreadyExistsError,
}


class SqlaFlusher(Flusher):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flush(self) -> None:
        try:
            await self._session.flush()
            logger.debug("%s.", DB_FLUSH_DONE)

        except IntegrityError as e:
            # str(e) carries the SQL statement's parameters and Postgres's
            # DETAIL line (an email, a phone number, a password hash), so it
            # is used only for matching here and never logged or attached
            # (docs/plans/15-upstream-autumn-2026.md, Step 3; OWASP's Logging
            # Cheat Sheet: keep personal data out of logs).
            msg = str(e)
            for name, exc_type in CONSTRAINT_TO_ERROR.items():
                if name in msg:
                    # `from None`, as upstream: the friendly 409 error doesn't
                    # carry the database error, so nothing can log it later.
                    raise exc_type from None

            # Only the violated constraint's name, which psycopg exposes as
            # e.orig.diag.constraint_name; read defensively, so a driver error
            # without it logs None instead of failing here.
            constraint_name = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
            logger.warning("Unhandled integrity error on constraint: %s", constraint_name)
            raise StorageError(DB_CONSTRAINT_VIOLATION) from e

        except SQLAlchemyError as e:
            raise StorageError(DB_FLUSH_FAILED) from e
