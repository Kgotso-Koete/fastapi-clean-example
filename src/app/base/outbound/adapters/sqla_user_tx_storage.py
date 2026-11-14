from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.commands.ports.user_tx_storage import UserTxStorage
from app.base.core.common.authorization.ports import AuthzUserFinder
from app.base.core.common.entities.types_ import UserId
from app.base.core.common.entities.user import User
from app.base.outbound.exceptions import StorageError


class SqlaUserTxStorage(UserTxStorage, AuthzUserFinder):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, user: User) -> None:
        try:
            self._session.add(user)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def get_by_id(
        self,
        user_id: UserId,
        *,
        for_update: bool = False,
    ) -> User | None:
        try:
            return await self._session.get(
                User,
                user_id,
                with_for_update=for_update,
            )
        except SQLAlchemyError as e:
            raise StorageError from e
