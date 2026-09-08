import asyncio

import click

from app.main.cli.container import build_cli_container, close_cli_container
from app.main.cli.users.group import make_users_group


@click.group()
@click.option("--username", "-u", envvar="APP_CLI_USERNAME", prompt=True)
@click.option("--password", "-p", envvar="APP_CLI_PASSWORD", prompt=True, hide_input=True)
@click.pass_context
def root_group(ctx: click.Context, username: str, password: str) -> None:
    """
    This app's CLI -- runs core commands/queries directly against the
    database, without HTTP/FastAPI involved. Prompts for --username/
    --password (or reads APP_CLI_USERNAME/APP_CLI_PASSWORD, for unattended/
    cron use, mirroring psql's PGPASSWORD precedent) and builds this
    invocation's one Dishka container up front; each subcommand resolves
    its own interactor from it, and verifying the credentials (via
    CurrentUserService -> CliIdentityProvider) happens lazily, the first
    time that subcommand actually needs the current user.
    """
    ctx.obj = {"container": build_cli_container(username=username, password=password)}
    ctx.call_on_close(lambda: asyncio.run(close_cli_container()))


root_group.add_command(make_users_group())
