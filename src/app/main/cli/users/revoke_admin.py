import asyncio
from uuid import UUID

import click

from app.core.commands.revoke_admin import RevokeAdmin, RevokeAdminRequest
from app.main.cli.errors import handle_errors


@click.command(name="revoke-admin")
@click.option("--user-id", type=click.UUID, required=True)
@click.pass_context
@handle_errors
def revoke_admin_command(ctx: click.Context, user_id: UUID) -> None:
    """Revoke admin rights from a subordinate admin (super admin only)."""

    async def _execute() -> None:
        async with ctx.obj["container"]() as request_container:
            interactor: RevokeAdmin = await request_container.get(RevokeAdmin)
            await interactor.execute(RevokeAdminRequest(user_id=user_id))

    asyncio.run(_execute())
    click.echo(f"Revoked admin from user {user_id}.")
