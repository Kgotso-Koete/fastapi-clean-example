from abc import abstractmethod
from typing import Protocol

from app.base.core.common.entities.types_ import UserId
from app.base.core.common.entities.user import User


class UserTxStorage(Protocol):
    """Transactional: commit required."""

    @abstractmethod
    def add(self, user: User) -> None: ...

    @abstractmethod
    async def get_by_id(
        self,
        user_id: UserId,
        *,
        for_update: bool = False,
    ) -> User | None: ...
