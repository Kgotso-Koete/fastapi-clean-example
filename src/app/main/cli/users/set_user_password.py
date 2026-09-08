import asyncio
from uuid import UUID

import click

from app.core.commands.set_user_password import SetUserPassword, SetUserPasswordRequest
from app.main.cli.errors import handle_errors


@click.command(name="set-user-password")
@click.option("--user-id", type=click.UUID, required=True)
@click.option("--password", prompt=True, hide_input=True)
@click.pass_context
@handle_errors
def set_user_password_command(
    ctx: click.Context,
    user_id: UUID,
    password: str,
) -> None:
    """Set a subordinate user's password (admin only)."""

    async def _execute() -> None:
        async with ctx.obj["container"]() as request_container:
            interactor: SetUserPassword = await request_container.get(SetUserPassword)
            await interactor.execute(SetUserPasswordRequest(user_id=user_id, password=password))

    asyncio.run(_execute())
    click.echo(f"Password set for user {user_id}.")
