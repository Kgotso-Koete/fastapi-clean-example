import uuid

import pytest
from click.testing import CliRunner
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.types_ import UserRole
from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.main.cli.root_group import root_group
from tests.integration.with_infra.factories import create_user_with_password


@pytest.fixture
async def it_cli_inactive_user(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> User:
    user = await create_user_with_password(it_user_service, role=UserRole.USER, is_active=False)
    it_session.add(user)
    await it_session.commit()
    return user


def test_returns_0_and_activates_a_subordinate_user(
    it_cli_admin: User,
    it_cli_raw_password: str,
    it_cli_inactive_user: User,
) -> None:
    result = CliRunner().invoke(
        root_group,
        [
            "--username",
            it_cli_admin.username.value,
            "--password",
            it_cli_raw_password,
            "users",
            "activate-user",
            "--user-id",
            str(it_cli_inactive_user.id_),
        ],
    )

    assert result.exit_code == 0, result.output
    assert str(it_cli_inactive_user.id_) in result.output


def test_returns_nonzero_when_the_user_is_not_found(
    it_cli_admin: User,
    it_cli_raw_password: str,
) -> None:
    result = CliRunner().invoke(
        root_group,
        [
            "--username",
            it_cli_admin.username.value,
            "--password",
            it_cli_raw_password,
            "users",
            "activate-user",
            "--user-id",
            str(uuid.uuid4()),
        ],
    )

    assert result.exit_code != 0
    assert "User not found" in result.output
