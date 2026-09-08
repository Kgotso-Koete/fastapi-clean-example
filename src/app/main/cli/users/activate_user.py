import asyncio
from uuid import UUID

import click

from app.core.commands.activate_user import ActivateUser, ActivateUserRequest
from app.main.cli.errors import handle_errors


@click.command(name="activate-user")
@click.option("--user-id", type=click.UUID, required=True)
@click.pass_context
@handle_errors
def activate_user_command(ctx: click.Context, user_id: UUID) -> None:
    """Restore a previously soft-deleted, subordinate user (admin only)."""

    async def _execute() -> None:
        async with ctx.obj["container"]() as request_container:
            interactor: ActivateUser = await request_container.get(ActivateUser)
            await interactor.execute(ActivateUserRequest(user_id=user_id))

    asyncio.run(_execute())
    click.echo(f"Activated user {user_id}.")
