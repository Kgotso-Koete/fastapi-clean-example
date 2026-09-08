import click

from app.main.cli.users.activate_user import activate_user_command
from app.main.cli.users.create_user import create_user_command
from app.main.cli.users.deactivate_user import deactivate_user_command
from app.main.cli.users.grant_admin import grant_admin_command
from app.main.cli.users.list_users import list_users_command
from app.main.cli.users.revoke_admin import revoke_admin_command
from app.main.cli.users.set_user_password import set_user_password_command


def make_users_group() -> click.Group:
    @click.group(name="users")
    def users_group() -> None:
        """User management commands."""

    users_group.add_command(list_users_command)
    users_group.add_command(create_user_command)
    users_group.add_command(set_user_password_command)
    users_group.add_command(grant_admin_command)
    users_group.add_command(revoke_admin_command)
    users_group.add_command(activate_user_command)
    users_group.add_command(deactivate_user_command)
    return users_group
