from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.services.user import UserService
from tests.integration.with_infra.organizations.constants import ORGANIZATIONS_ENDPOINT
from tests.integration.with_infra.organizations.helpers import (
    add_membership,
    create_organization_as,
    find_membership,
    log_in,
    members_url,
    new_account,
)

# DeleteOrganization end to end (docs/plans/9-organizations.md, Step 11):
# DELETE /api/v1/organizations/{organization_id}/, through the real HTTP stack,
# DI container and Postgres. The unit tests pin the rules; these prove the
# route, its status codes, and that the database cascade really empties the
# organization.


def _organization_url(organization_id: UUID) -> str:
    return f"{ORGANIZATIONS_ENDPOINT}{organization_id}/"


async def _find_organization(it_session: AsyncSession, organization_id: UUID) -> Organization | None:
    # Always re-read from Postgres: the route ran in its own session.
    it_session.expire_all()
    return await it_session.get(Organization, OrganizationId(organization_id))


async def test_an_owner_deletes_the_organization_and_every_membership_goes_with_it(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    member_membership_id = await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    invitation_id = await add_membership(it_session, organization_id, invitee, OrganizationRole.MEMBER, accepted=False)
    # create_organization_as() leaves the owner logged in.

    r = await it_client.delete(_organization_url(organization_id))

    assert r.status_code == 204
    assert await _find_organization(it_session, organization_id) is None
    # ON DELETE CASCADE: the accepted membership and the pending invitation
    # are gone too, with no Python code deleting them.
    assert await find_membership(it_session, member_membership_id) is None
    assert await find_membership(it_session, invitation_id) is None
    # A former member now gets what any outsider gets.
    await log_in(it_client, member)
    after = await it_client.get(members_url(organization_id))
    assert after.status_code == 404


@pytest.mark.parametrize(
    "role",
    [
        pytest.param(OrganizationRole.ADMIN, id="admin"),
        pytest.param(OrganizationRole.MEMBER, id="member"),
    ],
)
async def test_an_admin_or_member_gets_403_and_the_organization_survives(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
    role: OrganizationRole,
) -> None:
    owner = await new_account(it_session, it_user_service)
    caller = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, caller, role)
    await log_in(it_client, caller)

    r = await it_client.delete(_organization_url(organization_id))

    assert r.status_code == 403
    assert await _find_organization(it_session, organization_id) is not None


async def test_an_outsider_gets_404(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    outsider = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await log_in(it_client, outsider)

    r = await it_client.delete(_organization_url(organization_id))

    assert r.status_code == 404
    # The use case's own message -- a missing route's generic 404 can't
    # produce it, so this can't pass by accident.
    assert "Organization not found." in r.text
    assert await _find_organization(it_session, organization_id) is not None


async def test_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.delete(_organization_url(UUID(int=1)))

    assert r.status_code == 401
