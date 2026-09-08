import uuid

from click.testing import CliRunner

from app.core.common.entities.user import User
from app.main.cli.root_group import root_group


def test_returns_0_and_revokes_admin_from_a_subordinate_admin(
    it_cli_super_admin: User,
    it_cli_raw_password: str,
    it_cli_admin: User,
) -> None:
    result = CliRunner().invoke(
        root_group,
        [
            "--username",
            it_cli_super_admin.username.value,
            "--password",
            it_cli_raw_password,
            "users",
            "revoke-admin",
            "--user-id",
            str(it_cli_admin.id_),
        ],
    )

    assert result.exit_code == 0, result.output
    assert str(it_cli_admin.id_) in result.output


def test_returns_nonzero_when_the_user_is_not_found(
    it_cli_super_admin: User,
    it_cli_raw_password: str,
) -> None:
    result = CliRunner().invoke(
        root_group,
        [
            "--username",
            it_cli_super_admin.username.value,
            "--password",
            it_cli_raw_password,
            "users",
            "revoke-admin",
            "--user-id",
            str(uuid.uuid4()),
        ],
    )

    assert result.exit_code != 0
    assert "User not found" in result.output


def test_returns_nonzero_when_an_admin_tries_to_revoke_admin(
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
            "revoke-admin",
            "--user-id",
            str(it_cli_user.id_),
        ],
    )

    assert result.exit_code != 0
    assert "Not authorized" in result.output
