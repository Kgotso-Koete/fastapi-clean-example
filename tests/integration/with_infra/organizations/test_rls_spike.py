from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import Organization
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.integration.with_infra.organizations.helpers import Account, add_membership, new_account

# Row-Level Security SPIKE (docs/plans/9-organizations.md, Step 9) -- an
# experiment, not production wiring. It proves a Postgres RLS policy keyed on
# a session variable (app.current_organization_id) hides other organizations'
# membership rows even when a query forgets its WHERE organization_id = ...
#
# Nothing here touches the real schema permanently: every policy, grant and
# role is created inside one transaction and rolled back at the end, since
# Postgres DDL (CREATE POLICY, CREATE ROLE, ALTER TABLE ... ENABLE RLS) is
# transactional.
#
# The mechanism under test: set_config('app.current_organization_id', ..., true)
# -- the `true` makes it transaction-local (like SET LOCAL), so the value can
# never leak into the next request that reuses the pooled connection.

_ROLE = "rls_spike_role"


async def _persist_organization(it_session: AsyncSession, owner: Account, name: str) -> UUID:
    organization = Organization(
        id_=create_organization_id(),
        name=OrganizationName(name),
        description=Description(f"The {name}."),
        created_by_user_id=owner.user_id,
        created_at=UtcDatetime(datetime.now(UTC)),
    )
    it_session.add(organization)
    await it_session.commit()
    return organization.id_


async def _two_organizations_with_a_member_each(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> tuple[UUID, UUID]:
    owner_a = await new_account(it_session, it_user_service)
    owner_b = await new_account(it_session, it_user_service)
    organization_a = await _persist_organization(it_session, owner_a, "Avengers")
    organization_b = await _persist_organization(it_session, owner_b, "X-Men")
    await add_membership(it_session, organization_a, owner_a, OrganizationRole.OWNER)
    await add_membership(it_session, organization_b, owner_b, OrganizationRole.OWNER)
    return organization_a, organization_b


async def _enable_the_policy(it_session: AsyncSession) -> None:
    # current_setting(..., true) returns NULL when the variable is unset,
    # instead of raising -- so a request that never set it sees NO rows
    # (fails closed), rather than erroring or seeing everything.
    for statement in (
        f"CREATE ROLE {_ROLE} NOLOGIN",
        f"GRANT SELECT ON organization_memberships TO {_ROLE}",
        "ALTER TABLE organization_memberships ENABLE ROW LEVEL SECURITY",
        (
            "CREATE POLICY organization_isolation ON organization_memberships "
            "USING (organization_id = current_setting('app.current_organization_id', true)::uuid)"
        ),
    ):
        await it_session.execute(text(statement))


async def _visible_organization_ids(it_session: AsyncSession) -> set[UUID]:
    # Deliberately NO WHERE organization_id = ... -- the "forgotten filter"
    # this second layer exists to catch.
    result = await it_session.execute(text("SELECT organization_id FROM organization_memberships"))
    return set(result.scalars().all())


async def test_an_ordinary_role_sees_only_the_current_organizations_rows(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)
    try:
        await _enable_the_policy(it_session)
        await it_session.execute(text(f"SET LOCAL ROLE {_ROLE}"))
        await it_session.execute(
            text("SELECT set_config('app.current_organization_id', :organization_id, true)"),
            {"organization_id": str(organization_a)},
        )

        visible = await _visible_organization_ids(it_session)
    finally:
        await it_session.rollback()

    # Organization B's row exists, but is invisible to a request scoped to A.
    assert visible == {organization_a}
    assert organization_b not in visible


async def test_an_unset_organization_fails_closed_with_no_rows(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    await _two_organizations_with_a_member_each(it_session, it_user_service)
    try:
        await _enable_the_policy(it_session)
        await it_session.execute(text(f"SET LOCAL ROLE {_ROLE}"))

        visible = await _visible_organization_ids(it_session)
    finally:
        await it_session.rollback()

    assert visible == set()


async def test_a_superuser_bypasses_row_level_security(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # The finding that matters most for a real rollout: the app currently
    # connects as a superuser (postgres), and superusers IGNORE every RLS
    # policy -- even with the variable set to organization A, both rows are
    # returned. Real enforcement needs the app to connect as a
    # non-superuser, non-owner role.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)
    try:
        await _enable_the_policy(it_session)
        await it_session.execute(
            text("SELECT set_config('app.current_organization_id', :organization_id, true)"),
            {"organization_id": str(organization_a)},
        )

        visible = await _visible_organization_ids(it_session)
    finally:
        await it_session.rollback()

    assert visible == {organization_a, organization_b}
