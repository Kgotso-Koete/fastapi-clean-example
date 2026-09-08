import asyncio
import json
from dataclasses import asdict

import click

from app.core.queries.list_users import ListUsers, ListUsersRequest, UserSortingField
from app.core.queries.ports.user_reader import ListUsersQm
from app.core.queries.query_support.sorting import SortingOrder
from app.main.cli.errors import handle_errors


@click.command(name="list")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option(
    "--sort-by",
    "sorting_field",
    type=click.Choice([field.value for field in UserSortingField]),
    default=UserSortingField.UPDATED_AT.value,
    show_default=True,
)
@click.option(
    "--order",
    "sorting_order",
    type=click.Choice([order.value for order in SortingOrder]),
    default=SortingOrder.DESC.value,
    show_default=True,
)
@click.pass_context
@handle_errors
def list_users_command(
    ctx: click.Context,
    limit: int,
    offset: int,
    sorting_field: str,
    sorting_order: str,
) -> None:
    """List existing users, paginated (admin only)."""

    async def _execute() -> ListUsersQm:
        async with ctx.obj["container"]() as request_container:
            interactor: ListUsers = await request_container.get(ListUsers)
            return await interactor.execute(
                ListUsersRequest(
                    limit=limit,
                    offset=offset,
                    sorting_field=UserSortingField(sorting_field),
                    sorting_order=SortingOrder(sorting_order),
                )
            )

    result = asyncio.run(_execute())
    # json.dumps(result, default=str) would call str() on each *whole*
    # UserQm (default only fires for objects it can't serialize directly),
    # falling back to the dataclass's repr -- asdict() first gives it a
    # plain nested dict so only the individual UUID/datetime/enum leaves
    # need default=str, producing readable JSON instead of repr strings.
    users_as_dicts = [asdict(user) for user in result["users"]]
    click.echo(json.dumps({**result, "users": users_as_dicts}, indent=2, default=str))
