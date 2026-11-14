from abc import abstractmethod
from typing import Protocol

from app.base.core.common.entities.user import User
from app.base.core.common.value_objects.email import Email
from app.base.core.common.value_objects.username import Username


class UserFinder(Protocol):
    @abstractmethod
    async def find_by_username(self, username: Username) -> User | None: ...

    @abstractmethod
    async def find_by_email(self, email: Email) -> User | None: ...
