import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.services.user import UserService
from tests.integration.with_infra.organizations.helpers import (
    add_membership,
    create_organization_as,
    log_in,
    members_url,
    new_account,
)

# docs/plans/14-row-level-security.md, "Order of work": the app itself running
# as app_user.
#
# The SQL matrix (test_isolation_matrix.py) shows each policy does what it
# says. These tests show the policies are the right ones for the app: real
# routes, end to end, with the app's database login switched to app_user, so
# every query the app makes is filtered exactly as it will be in production.
# Setup (accounts, organizations, memberships) goes through the owner app
# (it_client, it_session); only the requests under test go through the
# runtime app (runtime_client).


async def test_a_member_lists_the_organizations_members_with_the_app_running_as_app_user(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_client: httpx2.AsyncClient,
) -> None:
    # The tracer bullet: one real route through every layer. The request
    # checks the session cookie, loads the user, checks the membership (with
    # no organization bound yet) and lists the members (with it bound).
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await add_membership(it_session, organization_id, invitee, OrganizationRole.MEMBER, accepted=False)
    await log_in(runtime_client, member)

    r = await runtime_client.get(members_url(organization_id))

    # The same expectations as the existing owner-app test of this route.
    assert r.status_code == 200
    body = r.json()
    assert sorted(m["username"] for m in body["members"]) == sorted(
        [owner.username, member.username, invitee.username],
    )
    assert body["total"] == 3
    assert body["member_count"] == 2
