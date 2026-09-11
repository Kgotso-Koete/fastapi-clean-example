import json

import pytest
from click.testing import CliRunner
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.main.cli.root_group import root_group
from tests.integration.with_infra.factories import (
    create_raw_email,
    create_raw_phone_number,
    create_raw_username,
    create_user,
)


def _create_user_args(*, username: str, role: str = "user") -> list[str]:
    return [
        "users",
        "create-user",
        "--username",
        username,
        "--email",
        create_raw_email(),
        "--phone-number",
        create_raw_phone_number(),
        "--role",
        role,
    ]


@pytest.fixture
async def it_cli_existing_user(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> str:
    """A user already persisted with a known username, for conflict tests."""
    username = create_raw_username()
    existing = create_user(it_user_service, raw_username=username)
    it_session.add(existing)
    await it_session.commit()
    return username


def test_returns_0_and_creates_a_user_for_an_authenticated_admin(
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
            *_create_user_args(username=create_raw_username()),
        ],
        input="a-brand-new-password1\n",
    )

    assert result.exit_code == 0, result.output
    # result.output includes the echoed "Password: " prompt text ahead of
    # the actual JSON, since CliRunner captures both on the same stream.
    body = json.loads(result.output[result.output.index("{") :])
    assert "id" in body
    assert "created_at" in body


def test_returns_nonzero_when_an_admin_tries_to_create_an_admin(
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
            *_create_user_args(username=create_raw_username(), role="admin"),
        ],
        input="a-brand-new-password1\n",
    )

    assert result.exit_code != 0
    assert "Not authorized" in result.output


def test_returns_nonzero_when_the_username_already_exists(
    it_cli_admin: User,
    it_cli_raw_password: str,
    it_cli_existing_user: str,
) -> None:
    result = CliRunner().invoke(
        root_group,
        [
            "--username",
            it_cli_admin.username.value,
            "--password",
            it_cli_raw_password,
            *_create_user_args(username=it_cli_existing_user),
        ],
        input="a-brand-new-password1\n",
    )

    assert result.exit_code != 0
    assert "Username already exists" in result.output
