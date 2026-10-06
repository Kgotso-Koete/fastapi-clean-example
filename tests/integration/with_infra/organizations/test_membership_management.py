from uuid import UUID, uuid4

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from tests.integration.with_infra.organizations.helpers import (
    add_membership,
    create_organization_as,
    find_membership,
    find_membership_id_for_user,
    log_in,
    member_url,
    new_account,
)

# Removing members, leaving, and changing roles end to end
# (docs/plans/9-organizations.md, Step 7): the DELETE and PATCH
# .../members/{membership_id}/ routes, through the real HTTP stack, DI
# container and Postgres. The rules themselves are unit-tested in
# tests/unit/core/commands/organizations/; these tests prove the wiring and
# the HTTP status codes. Asserting each error's own message means a missing
# route's generic 404 can never pass for a real one.


# --- Remove / leave (DELETE) --------------------------------------------------


async def test_remove_returns_204_and_an_admin_removes_a_member(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    admin = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, admin, OrganizationRole.ADMIN)
    membership_id = await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await log_in(it_client, admin)

    r = await it_client.delete(member_url(organization_id, membership_id))

    assert r.status_code == 204
    assert await find_membership(it_session, membership_id) is None


async def test_remove_returns_204_when_a_member_leaves(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await log_in(it_client, member)

    r = await it_client.delete(member_url(organization_id, membership_id))

    assert r.status_code == 204
    assert await find_membership(it_session, membership_id) is None


async def test_remove_returns_409_when_the_last_owner_tries_to_leave(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The real count_owners() query decides this, against real rows.
    owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    owner_membership_id = await find_membership_id_for_user(it_session, organization_id, owner.user_id)

    r = await it_client.delete(member_url(organization_id, owner_membership_id))

    assert r.status_code == 409
    assert "The organization's last owner cannot be removed or demoted." in r.text
    assert await find_membership(it_session, owner_membership_id) is not None


async def test_remove_returns_409_when_the_only_other_owner_is_deactivated(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Two OWNER rows, but one belongs to an account a platform admin has
    # deactivated -- it can't log in, so it can't run the organization. The
    # active owner is therefore the LAST real owner and mustn't be able to
    # leave, or the organization is left with nobody able to manage it.
    owner = await new_account(it_session, it_user_service)
    deactivated_owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, deactivated_owner, OrganizationRole.OWNER)
    deactivated = await it_session.get(User, deactivated_owner.user_id)
    assert deactivated is not None
    deactivated.is_active = False
    await it_session.commit()
    owner_membership_id = await find_membership_id_for_user(it_session, organization_id, owner.user_id)
    # create_organization_as() leaves the active owner logged in.

    r = await it_client.delete(member_url(organization_id, owner_membership_id))

    assert r.status_code == 409
    assert "The organization's last owner cannot be removed or demoted." in r.text
    assert await find_membership(it_session, owner_membership_id) is not None


async def test_remove_returns_403_when_a_member_removes_someone_else(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    other = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    other_membership_id = await add_membership(it_session, organization_id, other, OrganizationRole.MEMBER)
    await log_in(it_client, member)

    r = await it_client.delete(member_url(organization_id, other_membership_id))

    assert r.status_code == 403
    assert await find_membership(it_session, other_membership_id) is not None


async def test_remove_returns_403_when_an_admin_removes_an_owner(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    admin = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    owner_membership_id = await find_membership_id_for_user(it_session, organization_id, owner.user_id)
    await add_membership(it_session, organization_id, admin, OrganizationRole.ADMIN)
    await log_in(it_client, admin)

    r = await it_client.delete(member_url(organization_id, owner_membership_id))

    assert r.status_code == 403
    assert "Only an owner can remove or change another owner." in r.text


async def test_remove_returns_404_for_an_outsider(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    outsider = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    owner_membership_id = await find_membership_id_for_user(it_session, organization_id, owner.user_id)
    await log_in(it_client, outsider)

    r = await it_client.delete(member_url(organization_id, owner_membership_id))

    assert r.status_code == 404
    assert "Organization not found." in r.text


async def test_remove_returns_404_for_an_unknown_membership(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)

    r = await it_client.delete(member_url(organization_id, uuid4()))

    assert r.status_code == 404
    assert "Membership not found." in r.text


async def test_remove_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.delete(member_url(UUID(int=1), UUID(int=2)))

    assert r.status_code == 401


# --- Change role (PATCH) -------------------------------------------------------


async def test_change_role_returns_204_and_stores_the_new_role(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)

    r = await it_client.patch(member_url(organization_id, membership_id), json={"role": "admin"})

    assert r.status_code == 204
    membership = await find_membership(it_session, membership_id)
    assert membership is not None
    assert membership.role == OrganizationRole.ADMIN


async def test_change_role_returns_403_when_an_admin_grants_owner(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    admin = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, admin, OrganizationRole.ADMIN)
    membership_id = await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await log_in(it_client, admin)

    r = await it_client.patch(member_url(organization_id, membership_id), json={"role": "owner"})

    assert r.status_code == 403
    assert "Only an owner can grant the owner role." in r.text


async def test_change_role_returns_409_when_the_last_owner_demotes_themselves(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    owner_membership_id = await find_membership_id_for_user(it_session, organization_id, owner.user_id)

    r = await it_client.patch(member_url(organization_id, owner_membership_id), json={"role": "admin"})

    assert r.status_code == 409
    assert "The organization's last owner cannot be removed or demoted." in r.text


async def test_change_role_returns_422_for_an_unknown_role(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The body's role is validated against OrganizationRole before the use
    # case ever runs.
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    membership_id = await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)

    r = await it_client.patch(member_url(organization_id, membership_id), json={"role": "emperor"})

    assert r.status_code == 422
