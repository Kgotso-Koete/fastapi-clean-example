from uuid import UUID

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.services.user import UserService
from tests.integration.with_infra.organizations.constants import ORGANIZATIONS_ENDPOINT
from tests.integration.with_infra.organizations.helpers import (
    add_membership,
    create_organization_as,
    log_in,
    members_url,
    new_account,
)

# The three list routes end to end (docs/plans/9-organizations.md, Step 8):
# GET /organizations/, GET /organizations/invitations/ and
# GET /organizations/{organization_id}/members/, through the real HTTP stack,
# DI container and Postgres. The reader's SQL is tested directly in
# test_sqla_organization_reader.py and the use cases in tests/unit; these
# tests prove the wiring, the scoping and the HTTP status codes.

INVITATIONS_ENDPOINT = f"{ORGANIZATIONS_ENDPOINT}invitations/"


# --- GET /organizations/ (ListMyOrganizations) ---------------------------------


async def test_list_my_organizations_returns_200_with_the_description_my_role_and_member_count(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    # A pending invitation elsewhere is NOT an organization the member is in.
    other_owner = await new_account(it_session, it_user_service)
    other_organization_id = await create_organization_as(it_client, other_owner)
    await add_membership(it_session, other_organization_id, member, OrganizationRole.MEMBER, accepted=False)
    await log_in(it_client, member)

    r = await it_client.get(ORGANIZATIONS_ENDPOINT)

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    [organization] = body["organizations"]
    assert UUID(organization["id"]) == organization_id
    # What create_organization_as describes every organization as.
    assert organization["description"] == "Earth's mightiest heroes."
    assert organization["role"] == "member"
    # The owner and this member: two accepted memberships.
    assert organization["member_count"] == 2


async def test_list_my_organizations_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.get(ORGANIZATIONS_ENDPOINT)

    assert r.status_code == 401


# --- GET /organizations/invitations/ (ListMyInvitations) -----------------------


async def test_list_my_invitations_returns_200_with_the_description_and_the_ids_the_accept_route_needs(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = await add_membership(it_session, organization_id, invitee, OrganizationRole.ADMIN, accepted=False)
    await log_in(it_client, invitee)

    r = await it_client.get(INVITATIONS_ENDPOINT)

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    [invitation] = body["invitations"]
    assert UUID(invitation["organization_id"]) == organization_id
    assert UUID(invitation["membership_id"]) == membership_id
    # What the invitee reads before deciding to accept -- the description
    # create_organization_as gives every organization.
    assert invitation["organization_description"] == "Earth's mightiest heroes."
    assert invitation["role"] == "admin"
    assert invitation["expires_at"] is not None


async def test_list_my_invitations_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.get(INVITATIONS_ENDPOINT)

    assert r.status_code == 401


# --- GET /organizations/{id}/members/ (ListOrganizationMembers) ----------------


async def test_list_members_returns_200_for_a_plain_member_with_usernames_only(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A plain MEMBER may see who else is in their organization -- not just
    # an OWNER or ADMIN -- but never anyone's email or phone number.
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    invitee = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await add_membership(it_session, organization_id, invitee, OrganizationRole.MEMBER, accepted=False)
    await log_in(it_client, member)

    r = await it_client.get(members_url(organization_id))

    assert r.status_code == 200
    body = r.json()
    assert sorted(m["username"] for m in body["members"]) == sorted([owner.username, member.username, invitee.username])
    # Three rows listed (the pending invite included), two actual members.
    assert body["total"] == 3
    assert body["member_count"] == 2
    assert owner.email not in r.text
    assert member.email not in r.text


async def test_list_members_returns_404_for_an_outsider(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    outsider = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await log_in(it_client, outsider)

    r = await it_client.get(members_url(organization_id))

    assert r.status_code == 404
    assert "Organization not found." in r.text


async def test_list_members_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.get(members_url(UUID(int=1)))

    assert r.status_code == 401
