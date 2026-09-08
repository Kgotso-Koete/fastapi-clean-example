import asyncio
from uuid import UUID

import click

from app.core.commands.deactivate_user import DeactivateUser, DeactivateUserRequest
from app.main.cli.errors import handle_errors


@click.command(name="deactivate-user")
@click.option("--user-id", type=click.UUID, required=True)
@click.pass_context
@handle_errors
def deactivate_user_command(ctx: click.Context, user_id: UUID) -> None:
    """Soft-delete a subordinate user (admin only)."""

    async def _execute() -> None:
        async with ctx.obj["container"]() as request_container:
            interactor: DeactivateUser = await request_container.get(DeactivateUser)
            await interactor.execute(DeactivateUserRequest(user_id=user_id))

    asyncio.run(_execute())
    click.echo(f"Deactivated user {user_id}.")
