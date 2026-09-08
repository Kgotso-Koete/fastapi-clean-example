import uuid

from click.testing import CliRunner

from app.core.common.entities.user import User
from app.main.cli.root_group import root_group


def test_returns_0_and_deactivates_a_subordinate_user(
    it_cli_admin: User,
    it_cli_raw_password: str,
    it_cli_user: User,
) -> None:
    result = CliRunner().invoke(
        root_group,
        [
            "--username",
            it_cli_admin.username.value,
            "--password",
            it_cli_raw_password,
            "users",
            "deactivate-user",
            "--user-id",
            str(it_cli_user.id_),
        ],
    )

    assert result.exit_code == 0, result.output
    assert str(it_cli_user.id_) in result.output


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
            "deactivate-user",
            "--user-id",
            str(uuid.uuid4()),
        ],
    )

    assert result.exit_code != 0
    assert "User not found" in result.output
