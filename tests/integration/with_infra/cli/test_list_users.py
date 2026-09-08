import subprocess
import sys

from click.testing import CliRunner

from app.core.common.entities.user import User
from app.main.cli.root_group import root_group


def test_returns_0_and_lists_users_for_an_authenticated_admin(
    it_cli_admin: User,
    it_cli_raw_password: str,
) -> None:
    result = CliRunner().invoke(
        root_group,
        ["--username", it_cli_admin.username.value, "--password", it_cli_raw_password, "users", "list"],
    )

    assert result.exit_code == 0, result.output
    assert it_cli_admin.username.value in result.output


def test_exits_nonzero_for_an_unknown_username() -> None:
    result = CliRunner().invoke(
        root_group,
        ["--username", "no-such-user", "--password", "irrelevant1", "users", "list"],
    )

    assert result.exit_code != 0
    assert "Invalid username or password" in result.output


def test_exits_nonzero_for_the_wrong_password(it_cli_admin: User) -> None:
    result = CliRunner().invoke(
        root_group,
        ["--username", it_cli_admin.username.value, "--password", "definitely-the-wrong-one", "users", "list"],
    )

    assert result.exit_code != 0
    assert "Invalid username or password" in result.output


def test_exits_nonzero_for_a_non_admin_actor(
    it_cli_user: User,
    it_cli_raw_password: str,
) -> None:
    result = CliRunner().invoke(
        root_group,
        ["--username", it_cli_user.username.value, "--password", it_cli_raw_password, "users", "list"],
    )

    assert result.exit_code != 0
    assert "Not authorized" in result.output


# The tests above all pass --username/--password as flags. None of them exercise
# the *prompted* path (no flags -- Click's `prompt=True`/`hide_input=True` reading
# from stdin), which is what a real operator actually types at the terminal. That
# gap is exactly where a manual run turned out to be silently broken.
def test_prompts_for_credentials_and_lists_users_when_flags_are_omitted(
    it_cli_admin: User,
    it_cli_raw_password: str,
) -> None:
    result = CliRunner().invoke(
        root_group,
        ["users", "list"],
        input=f"{it_cli_admin.username.value}\n{it_cli_raw_password}\n",
    )

    assert result.exit_code == 0, result.output
    assert it_cli_admin.username.value in result.output


def test_prompts_for_credentials_and_reports_an_error_for_the_wrong_password(
    it_cli_admin: User,
) -> None:
    result = CliRunner().invoke(
        root_group,
        ["users", "list"],
        input=f"{it_cli_admin.username.value}\ndefinitely-the-wrong-one\n",
    )

    assert result.exit_code != 0
    assert "Invalid username or password" in result.output


# CliRunner invokes root_group in-process -- it never proves the real
# `python -m app.main.cli` entrypoint (a genuine separate OS process, real
# stdin/stdout/stderr pipes, its own getpass.getpass() call for the hidden
# password prompt) actually works. This is the closest an automated test can
# get to that without a real pty.
def test_real_subprocess_lists_users_for_an_authenticated_admin(
    it_cli_admin: User,
    it_cli_raw_password: str,
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.main.cli", "users", "list"],
        input=f"{it_cli_admin.username.value}\n{it_cli_raw_password}\n",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert it_cli_admin.username.value in result.stdout


def test_real_subprocess_reports_an_error_for_the_wrong_password(
    it_cli_admin: User,
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.main.cli", "users", "list"],
        input=f"{it_cli_admin.username.value}\ndefinitely-the-wrong-one\n",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "Invalid username or password" in result.stderr
