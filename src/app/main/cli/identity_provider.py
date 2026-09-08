from typing import NewType

from app.core.common.entities.types_ import UserId
from app.core.common.ports.identity_provider import IdentityProvider
from app.core.common.ports.user_finder import UserFinder
from app.core.common.services.user import UserService
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.username import Username

# Distinct from plain `str` so Dishka can tell "--username" and "--password"
# apart when resolving CliIdentityProvider's constructor by type.
CliUsername = NewType("CliUsername", str)
CliPassword = NewType("CliPassword", str)


class CliIdentityError(Exception):
    """Raised when the CLI's --username/--password don't resolve to a real, matching user."""


class CliIdentityProvider(IdentityProvider):
    """
    The CLI's IdentityProvider: verifies a username/password pair (prompted by
    the root Click group) against the same UserService.is_password_valid()
    LogIn uses for HTTP login, instead of AuthSessionIdentityProvider's
    cookie/JWT session lookup. Whether the resolved user is *active* and
    *authorized* for a given command is still CurrentUserService's job, same
    as it is for every other IdentityProvider implementation.
    """

    def __init__(
        self,
        username: CliUsername,
        password: CliPassword,
        user_finder: UserFinder,
        user_service: UserService,
    ) -> None:
        self._username = username
        self._password = password
        self._user_finder = user_finder
        self._user_service = user_service

    async def get_current_user_id(self) -> UserId:
        user = await self._user_finder.find_by_username(Username(self._username))
        # Same error for "no such user" and "wrong password" -- a different
        # message per case would let a caller enumerate valid usernames.
        if user is None or not await self._user_service.is_password_valid(user, RawPassword(self._password)):
            raise CliIdentityError("Invalid username or password.")
        return user.id_
