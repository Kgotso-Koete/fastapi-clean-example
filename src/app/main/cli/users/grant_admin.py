import asyncio
from uuid import UUID

import click

from app.core.commands.grant_admin import GrantAdmin, GrantAdminRequest
from app.main.cli.errors import handle_errors


@click.command(name="grant-admin")
@click.option("--user-id", type=click.UUID, required=True)
@click.pass_context
@handle_errors
def grant_admin_command(ctx: click.Context, user_id: UUID) -> None:
    """Grant admin rights to a subordinate user (super admin only)."""

    async def _execute() -> None:
        async with ctx.obj["container"]() as request_container:
            interactor: GrantAdmin = await request_container.get(GrantAdmin)
            await interactor.execute(GrantAdminRequest(user_id=user_id))

    asyncio.run(_execute())
    click.echo(f"Granted admin to user {user_id}.")
