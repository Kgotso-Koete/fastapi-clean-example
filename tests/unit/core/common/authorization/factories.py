from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.ports import AuthzUserFinder
from app.core.common.entities.types_ import UserId, UserRole
from app.core.common.entities.user import User
from app.core.common.ports.access_revoker import AccessRevoker
from app.core.common.ports.identity_provider import IdentityProvider
from tests.unit.core.common.services.factories import create_super_user, create_user


def make_super_admin() -> User:
    return create_super_user()


def make_admin() -> User:
    return create_user(role=UserRole.ADMIN)


def make_user() -> User:
    return create_user(role=UserRole.USER)


# --- CurrentUserService fakes ---
# CurrentUserService is a concrete class, not a Protocol, so it can't be
# faked by duck-typing a lookalike (mypy --strict would reject passing one
# where CurrentUserService is annotated) -- instead, construct a REAL
# CurrentUserService backed by fake ports, exactly mirroring how it's
# actually wired in production, just with fakes standing in for
# IdentityProvider/AuthzUserFinder/AccessRevoker.


class FakeIdentityProvider(IdentityProvider):
    def __init__(self, user_id: UserId) -> None:
        self._user_id = user_id

    async def get_current_user_id(self) -> UserId:
        return self._user_id


class FakeAuthzUserFinder(AuthzUserFinder):
    """Returns a fixed user (or None), regardless of the id asked for."""

    def __init__(self, user: User | None) -> None:
        self._user = user

    async def get_by_id(self, user_id: UserId, *, for_update: bool = False) -> User | None:
        return self._user


class FakeAccessRevoker(AccessRevoker):
    async def remove_all_user_access(self, user_id: UserId) -> None:
        pass


def create_current_user_service(user: User) -> CurrentUserService:
    """A CurrentUserService that resolves to the given user, for any
    interactor that depends on one."""
    return CurrentUserService(
        identity_provider=FakeIdentityProvider(user.id_),
        authz_user_finder=FakeAuthzUserFinder(user),
        access_revoker=FakeAccessRevoker(),
    )
