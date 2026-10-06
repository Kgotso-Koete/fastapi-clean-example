from uuid import UUID

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import Organization
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.outbound.persistence_sqla.mappings.organization_membership import organization_memberships_table
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_raw_password, create_user_with_password
from tests.integration.with_infra.organizations.constants import ORGANIZATIONS_ENDPOINT

# End-to-end through the real HTTP route, DI container and Postgres --
# mirrors tests/integration/with_infra/users/test_create_user.py. Any
# logged-in user (platform role USER is enough) may create an organization.

_DESCRIPTION = "Earth's mightiest heroes."


async def _log_in_as_new_user(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> User:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    return user


async def test_returns_201_and_the_creator_is_its_accepted_owner(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user = await _log_in_as_new_user(it_client, it_session, it_user_service)

    r = await it_client.post(
        ORGANIZATIONS_ENDPOINT,
        json={"name": "  Avengers  ", "description": f"  {_DESCRIPTION}\n"},
    )

    assert r.status_code == 201
    body = r.json()
    # The response carries the trimmed name and description, as stored.
    assert body["name"] == "Avengers"
    assert body["description"] == _DESCRIPTION
    assert "created_at" in body

    # The organization really exists in Postgres, owned by the caller...
    organization = await it_session.get(Organization, UUID(body["id"]))
    assert isinstance(organization, Organization)
    assert organization.name == OrganizationName("Avengers")
    assert organization.description == Description(_DESCRIPTION)
    assert organization.created_by_user_id == user.id_

    # ...and so does exactly one membership: the caller, as an already
    # accepted OWNER (no self-invite), committed in the same transaction.
    memberships = (
        await it_session.scalars(
            select(OrganizationMembership).where(organization_memberships_table.c.organization_id == organization.id_)
        )
    ).all()
    assert len(memberships) == 1
    assert memberships[0].user_id == user.id_
    assert memberships[0].role == OrganizationRole.OWNER
    assert memberships[0].is_accepted


async def test_returns_401_when_not_authenticated(
    it_client: httpx2.AsyncClient,
) -> None:
    r = await it_client.post(ORGANIZATIONS_ENDPOINT, json={"name": "Avengers", "description": _DESCRIPTION})

    assert r.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"description": _DESCRIPTION}, id="name_missing"),
        # Mandatory: every organization explains itself to the people it
        # invites, so leaving it out is as malformed as leaving out the name.
        pytest.param({"name": "Avengers"}, id="description_missing"),
    ],
)
async def test_returns_422_when_the_name_or_description_is_missing(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
    body: dict[str, str],
) -> None:
    # A structurally invalid request body -- rejected by FastAPI's own
    # request validation before the use case ever runs.
    await _log_in_as_new_user(it_client, it_session, it_user_service)

    r = await it_client.post(ORGANIZATIONS_ENDPOINT, json=body)

    assert r.status_code == 422


@pytest.mark.parametrize(
    ("name", "description"),
    [
        pytest.param("   ", _DESCRIPTION, id="blank_name"),
        pytest.param("S.H.I.E.L.D.", _DESCRIPTION, id="disallowed_character_in_name"),
        # Present, so FastAPI accepts it -- but blank, which Description's
        # own rules reject.
        pytest.param("Avengers", "   ", id="blank_description"),
    ],
)
async def test_returns_400_when_the_name_or_description_breaks_its_rules(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
    name: str,
    description: str,
) -> None:
    # A well-formed request whose name or description fails its value
    # object's domain rules -- BusinessTypeError maps to 400, the same way an
    # invalid Username does in test_create_user.py. Nothing may be created.
    await _log_in_as_new_user(it_client, it_session, it_user_service)

    r = await it_client.post(ORGANIZATIONS_ENDPOINT, json={"name": name, "description": description})

    assert r.status_code == 400
    assert (await it_session.scalars(select(Organization))).all() == []
