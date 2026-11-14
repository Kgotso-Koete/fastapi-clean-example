from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.common.entities.user import User
from app.base.core.common.value_objects.email import Email
from app.base.core.common.value_objects.username import Username
from app.base.outbound.exceptions import StorageError
from app.base.outbound.persistence_sqla.mappings.user import users_table


class SqlaUserFinder:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_username(self, username: Username) -> User | None:
        stmt = select(User).where(users_table.c.username == username.value)
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return result.scalar_one_or_none()

    async def find_by_email(self, email: Email) -> User | None:
        stmt = select(User).where(users_table.c.email == email.value)
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return result.scalar_one_or_none()
