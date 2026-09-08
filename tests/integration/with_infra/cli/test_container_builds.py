from collections.abc import AsyncIterator

import pytest
from dishka import AsyncContainer

from app.core.commands.activate_user import ActivateUser
from app.core.commands.create_user import CreateUser
from app.core.commands.deactivate_user import DeactivateUser
from app.core.commands.grant_admin import GrantAdmin
from app.core.commands.revoke_admin import RevokeAdmin
from app.core.commands.set_user_password import SetUserPassword
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.queries.list_users import ListUsers
from app.main.cli.container import build_cli_container, close_cli_container

# Resolving these doesn't call any of their methods (in particular, never
# calls IdentityProvider.get_current_user_id()), so the credentials never
# need to correspond to a real user for this test -- it only proves the
# container's declared graph builds and every interactor resolves cleanly,
# with no Request anywhere in it.
_PLACEHOLDER_USERNAME = "placeholder-user"
_PLACEHOLDER_PASSWORD = "placeholder-password"


@pytest.fixture
async def it_cli_container() -> AsyncIterator[AsyncContainer]:
    container = build_cli_container(username=_PLACEHOLDER_USERNAME, password=_PLACEHOLDER_PASSWORD)
    yield container
    await close_cli_container()


@pytest.mark.parametrize(
    "interactor_cls",
    [
        CurrentUserService,
        CreateUser,
        SetUserPassword,
        GrantAdmin,
        RevokeAdmin,
        ActivateUser,
        DeactivateUser,
        ListUsers,
    ],
)
async def test_resolves_every_cli_interactor_without_needing_a_request(
    it_cli_container: AsyncContainer,
    interactor_cls: type,
) -> None:
    async with it_cli_container() as request_container:
        resolved: object = await request_container.get(interactor_cls)

    assert isinstance(resolved, interactor_cls)
