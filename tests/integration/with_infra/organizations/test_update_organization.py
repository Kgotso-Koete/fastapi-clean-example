from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from tests.integration.with_infra.organizations.constants import ORGANIZATIONS_ENDPOINT
from tests.integration.with_infra.organizations.helpers import (
    add_membership,
    create_organization_as,
    log_in,
    new_account,
)

# UpdateOrganization end to end (docs/plans/9-organizations.md, Step 13):
# PATCH /api/v1/organizations/{organization_id}/, through the real HTTP stack,
# DI container and Postgres. The unit tests pin the rules; these prove the
# route, its status codes, and that the change really reaches the database.
#
# create_organization_as() always creates "Avengers", described as
# "Earth's mightiest heroes.".

_NAME = "Avengers"
_DESCRIPTION = "Earth's mightiest heroes."


def _organization_url(organization_id: UUID) -> str:
    return f"{ORGANIZATIONS_ENDPOINT}{organization_id}/"


async def _find_organization(it_session: AsyncSession, organization_id: UUID) -> Organization:
    # Always re-read from Postgres: the route ran in its own session.
    it_session.expire_all()
    organization = await it_session.get(Organization, OrganizationId(organization_id))
    assert organization is not None
    return organization


async def _assert_unchanged(it_session: AsyncSession, organization_id: UUID) -> None:
    organization = await _find_organization(it_session, organization_id)
    assert organization.name == OrganizationName(_NAME)
    assert organization.description == Description(_DESCRIPTION)


@pytest.mark.parametrize(
    "role",
    [
        pytest.param(OrganizationRole.ADMIN, id="admin"),
        pytest.param(OrganizationRole.OWNER, id="owner"),
    ],
)
async def test_an_admin_or_owner_gets_200_and_the_change_is_stored(
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

    r = await it_client.patch(
        _organization_url(organization_id),
        json={"name": "  New Avengers  ", "description": "Assembled again.\n"},
    )

    assert r.status_code == 200
    # The trimmed values, as stored.
    assert r.json() == {"id": str(organization_id), "name": "New Avengers", "description": "Assembled again."}
    organization = await _find_organization(it_session, organization_id)
    assert organization.name == OrganizationName("New Avengers")
    assert organization.description == Description("Assembled again.")


async def test_a_field_left_out_is_unchanged(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    # create_organization_as() leaves the owner logged in.

    r = await it_client.patch(_organization_url(organization_id), json={"description": "Assembled again."})

    assert r.status_code == 200
    organization = await _find_organization(it_session, organization_id)
    assert organization.name == OrganizationName(_NAME)
    assert organization.description == Description("Assembled again.")


async def test_a_blank_description_gets_400_and_nothing_changes(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The description is mandatory, so "clearing" it is just an invalid value
    # -- and the valid name sent with it must not be applied either.
    owner = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)

    r = await it_client.patch(
        _organization_url(organization_id),
        json={"name": "New Avengers", "description": "   "},
    )

    assert r.status_code == 400
    await _assert_unchanged(it_session, organization_id)


async def test_a_member_gets_403_and_nothing_changes(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    member = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await add_membership(it_session, organization_id, member, OrganizationRole.MEMBER)
    await log_in(it_client, member)

    r = await it_client.patch(_organization_url(organization_id), json={"name": "New Avengers"})

    assert r.status_code == 403
    await _assert_unchanged(it_session, organization_id)


async def test_an_outsider_gets_404_and_nothing_changes(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    owner = await new_account(it_session, it_user_service)
    outsider = await new_account(it_session, it_user_service)
    organization_id = await create_organization_as(it_client, owner)
    await log_in(it_client, outsider)

    r = await it_client.patch(_organization_url(organization_id), json={"name": "New Avengers"})

    assert r.status_code == 404
    # The use case's own message -- a missing route's generic 404 can't
    # produce it, so this can't pass by accident.
    assert "Organization not found." in r.text
    await _assert_unchanged(it_session, organization_id)


async def test_returns_401_when_not_authenticated(it_client: httpx2.AsyncClient) -> None:
    r = await it_client.patch(_organization_url(UUID(int=1)), json={"name": "New Avengers"})

    assert r.status_code == 401
