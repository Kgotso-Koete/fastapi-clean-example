from abc import abstractmethod
from typing import Protocol

from app.core.common.entities.user import User
from app.core.common.value_objects.username import Username


class UserFinder(Protocol):
    @abstractmethod
    async def find_by_username(self, username: Username) -> User | None: ...
