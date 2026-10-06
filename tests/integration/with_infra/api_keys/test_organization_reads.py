from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.services.user import UserService
from tests.integration.with_infra.organizations.constants import (
    ORGANIZATIONS_ENDPOINT as PRIVATE_ORGANIZATIONS_ENDPOINT,
)
from tests.integration.with_infra.organizations.helpers import (
    Account,
    add_membership,
    create_organization_as,
    log_in,
    members_url,
    new_account,
)

# The two read-only organization queries on the public API
# (docs/plans/9-organizations.md, Step 15): ListMyOrganizations and
# ListOrganizationMembers, authenticated by X-API-Key instead of a cookie.
# Like test_get_profile.py, the proof is that one account gets the exact
# same JSON through either app: the same query classes serve both
# entrypoints, and only the identity mechanism differs.

# No /public prefix -- see conftest.py's own note on this.
API_KEYS_ENDPOINT = "/v1/api-keys/"
ORGANIZATIONS_ENDPOINT = "/v1/organizations/"


def public_members_url(organization_id: UUID) -> str:
    # The public twin of helpers.members_url(), which builds /api/v1/... paths.
    return f"{ORGANIZATIONS_ENDPOINT}{organization_id}/members/"


async def _issue_key(client: httpx2.AsyncClient, account: Account) -> str:
    # A small copy of test_get_profile.py's helper: issues a real key through
    # the public route with the account's username and password, and returns
    # the raw key, which is only ever shown once.
    response = await client.post(
        API_KEYS_ENDPOINT,
        json={"identifier": account.username, "password": account.password, "expires_in_days": 30, "label": None},
    )
    assert response.status_code == 201
    return str(response.json()["raw_key"])


@pytest.mark.asyncio
async def test_list_my_organizations_returns_the_same_json_as_the_cookie_route(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_client: httpx2.AsyncClient,
    it_public_client: httpx2.AsyncClient,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)

    await log_in(it_client, member)
    private_response = await it_client.get(PRIVATE_ORGANIZATIONS_ENDPOINT)
    assert private_response.status_code == 200
    # Guard against comparing two empty lists: the member really is in one.
    assert private_response.json()["total"] == 1

    raw_key = await _issue_key(it_public_client, member)
    public_response = await it_public_client.get(ORGANIZATIONS_ENDPOINT, headers={"X-API-Key": raw_key})

    assert public_response.status_code == 200
    assert public_response.json() == private_response.json()


@pytest.mark.asyncio
async def test_list_organization_members_returns_the_same_json_as_the_cookie_route(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_client: httpx2.AsyncClient,
    it_public_client: httpx2.AsyncClient,
) -> None:
    # A plain MEMBER, the lowest role allowed to list members, and a pending
    # invitee, so the compared JSON includes both an accepted and a pending row.
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await add_membership(it_session, organization_id, invitee, OrganizationRole.MEMBER, accepted=False)

    await log_in(it_client, member)
    private_response = await it_client.get(members_url(organization_id))
    assert private_response.status_code == 200
    assert private_response.json()["total"] == 3

    raw_key = await _issue_key(it_public_client, member)
    public_response = await it_public_client.get(public_members_url(organization_id), headers={"X-API-Key": raw_key})

    assert public_response.status_code == 200
    assert public_response.json() == private_response.json()


@pytest.mark.asyncio
async def test_list_organization_members_returns_404_for_an_outsiders_key(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_client: httpx2.AsyncClient,
    it_public_client: httpx2.AsyncClient,
) -> None:
    # The same privacy rule as the cookie route: a valid key whose owner has
    # no membership can't confirm the organization exists. The message is
    # asserted too, so a 404 from a route that doesn't exist can't pass.
    owner = await new_account(it_session, it_user_service)
    outsider = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)

    raw_key = await _issue_key(it_public_client, outsider)
    response = await it_public_client.get(public_members_url(organization_id), headers={"X-API-Key": raw_key})

    assert response.status_code == 404
    assert "Organization not found." in response.text


@pytest.mark.asyncio
async def test_list_my_organizations_returns_401_for_a_missing_key(it_public_client: httpx2.AsyncClient) -> None:
    response = await it_public_client.get(ORGANIZATIONS_ENDPOINT)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_organization_members_returns_401_for_a_missing_key(it_public_client: httpx2.AsyncClient) -> None:
    # Any id will do: the request is refused before the organization is looked up.
    response = await it_public_client.get(public_members_url(UUID(int=1)))

    assert response.status_code == 401
