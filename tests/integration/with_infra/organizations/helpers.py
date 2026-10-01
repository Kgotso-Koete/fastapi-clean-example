from datetime import UTC, datetime
from uuid import UUID

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.entities.types_ import UserId
from app.core.common.entities.user import User
from app.core.common.factories.organization_membership_id_factory import create_organization_membership_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.persistence_sqla.mappings.organization_membership import organization_memberships_table
from tests.integration.with_infra.account.constants import AUTH_COOKIE_NAME, LOG_OUT_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_raw_password, create_user_with_password
from tests.integration.with_infra.organizations.constants import ORGANIZATIONS_ENDPOINT

# Shared helpers for the organizations integration tests: real accounts,
# switching the logged-in user, creating organizations through the real
# route, and reading memberships straight from Postgres.


class Account:
    """A persisted user's id, username and email, plus the raw password needed
    to log in as them. Plain values copied out up front, NOT the ORM User
    object: find_membership() expires everything in it_session, and reading an
    expired attribute would make SQLAlchemy lazy-load it synchronously, which
    async sessions forbid (MissingGreenlet)."""

    def __init__(self, user: User, password: str) -> None:
        self.user_id = user.id_
        self.username = user.username.value
        self.email = user.email.value
        self.password = password


async def new_account(it_session: AsyncSession, it_user_service: UserService) -> Account:
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    it_session.add(user)
    await it_session.commit()
    return Account(user, password)


async def log_in(it_client: httpx2.AsyncClient, account: Account) -> None:
    # The app refuses a login while a session is already active
    # (AlreadyAuthenticatedError, 403), so switching users on the same client
    # needs an explicit logout first (DELETE, like the real logout route) --
    # and it must succeed, so a broken logout fails loudly here.
    if it_client.cookies.get(AUTH_COOKIE_NAME) is not None:
        logged_out = await it_client.delete(LOG_OUT_ENDPOINT)
        assert logged_out.status_code == 204
    await authenticate(it_client, account.username, account.password)


async def create_organization_as(it_client: httpx2.AsyncClient, owner: Account) -> UUID:
    # Through the real route, so the owner's membership is exactly what
    # production creates. Leaves `owner` logged in.
    await log_in(it_client, owner)
    r = await it_client.post(ORGANIZATIONS_ENDPOINT, json={"name": "Avengers"})
    assert r.status_code == 201
    return UUID(r.json()["id"])


async def add_membership(
    it_session: AsyncSession,
    organization_id: UUID,
    account: Account,
    role: OrganizationRole,
    *,
    accepted: bool = True,
) -> UUID:
    # Directly in the database: how someone became a member isn't what these
    # tests are about. accepted=False makes a pending invitation instead.
    now = UtcDatetime(datetime.now(UTC))
    membership = OrganizationMembership(
        id_=create_organization_membership_id(),
        organization_id=OrganizationId(organization_id),
        user_id=account.user_id,
        role=role,
        invited_by_user_id=account.user_id,
        created_at=now,
        accepted_at=now if accepted else None,
        expires_at=None if accepted else UtcDatetime(datetime(2099, 1, 1, tzinfo=UTC)),
    )
    it_session.add(membership)
    await it_session.commit()
    return membership.id_


async def find_membership(it_session: AsyncSession, membership_id: UUID) -> OrganizationMembership | None:
    # Always re-read from Postgres: the routes run in their own session, so
    # anything cached in it_session could be stale.
    it_session.expire_all()
    result = await it_session.execute(
        select(OrganizationMembership).where(organization_memberships_table.c.id == membership_id)
    )
    return result.scalar_one_or_none()


async def find_membership_id_for_user(it_session: AsyncSession, organization_id: UUID, user_id: UserId) -> UUID:
    # E.g. the owner row CreateOrganization made, whose id no response returns.
    # Selects the mapped entity (not the bare id column, which mypy types as
    # Any) and returns its typed id_.
    result = await it_session.execute(
        select(OrganizationMembership)
        .where(organization_memberships_table.c.organization_id == organization_id)
        .where(organization_memberships_table.c.user_id == user_id)
    )
    return result.scalar_one().id_


def members_url(organization_id: UUID | str) -> str:
    return f"{ORGANIZATIONS_ENDPOINT}{organization_id}/members/"


def member_url(organization_id: UUID, membership_id: UUID) -> str:
    return f"{members_url(organization_id)}{membership_id}/"
