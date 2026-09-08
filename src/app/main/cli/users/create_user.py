import asyncio
import json

import click

from app.core.commands.create_user import CreateUser, CreateUserRequest, CreateUserResponse, UserRoleRequestEnum
from app.main.cli.errors import handle_errors


@click.command(name="create-user")
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option("--phone-number", required=True)
@click.option("--password", prompt=True, hide_input=True)
@click.option(
    "--role",
    type=click.Choice([role.value for role in UserRoleRequestEnum]),
    default=UserRoleRequestEnum.USER.value,
    show_default=True,
)
@click.pass_context
@handle_errors
def create_user_command(
    ctx: click.Context,
    username: str,
    email: str,
    phone_number: str,
    password: str,
    role: str,
) -> None:
    """Create a new user (admin only; only super admins may create admins)."""

    async def _execute() -> CreateUserResponse:
        async with ctx.obj["container"]() as request_container:
            interactor: CreateUser = await request_container.get(CreateUser)
            return await interactor.execute(
                CreateUserRequest(
                    username=username,
                    email=email,
                    phone_number=phone_number,
                    password=password,
                    role=UserRoleRequestEnum(role),
                )
            )

    result = asyncio.run(_execute())
    click.echo(json.dumps(result, indent=2, default=str))
