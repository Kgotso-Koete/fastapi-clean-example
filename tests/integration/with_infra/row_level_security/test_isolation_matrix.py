from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.common.entities.organization import Organization
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.integration.with_infra.organizations.helpers import Account, add_membership, new_account

# docs/plans/14-row-level-security.md, Step 3: the isolation matrix at the
# SQL level.
#
# Each test proves one cell of the allow-and-deny matrix (OWASP: "For each
# RLS-protected table, prove that expected cross-tenant operations are
# denied and expected same-tenant operations succeed"). Rows are seeded as
# the owner through it_session, which commits; every read and write under
# test goes through runtime_connection, a real login as the runtime role,
# because the owner bypasses every policy. The context is bound exactly as
# the app will bind it: set_config(..., true), local to one transaction.
#
# The queries deliberately leave out WHERE organization_id = ...: they are
# the "forgotten filter" this second layer of isolation exists to catch.


async def _persist_organization(it_session: AsyncSession, owner: Account, name: str) -> UUID:
    # Copied from the RLS spike (organizations/test_rls_spike.py), which this
    # step retires (plan 14, Decision 5).
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
    # Organization A and organization B, each with its owner as its only
    # accepted member, so each membership row belongs to exactly one of them.
    owner_a = await new_account(it_session, it_user_service)
    owner_b = await new_account(it_session, it_user_service)
    organization_a = await _persist_organization(it_session, owner_a, "Avengers")
    organization_b = await _persist_organization(it_session, owner_b, "X-Men")
    await add_membership(it_session, organization_a, owner_a, OrganizationRole.OWNER)
    await add_membership(it_session, organization_b, owner_b, OrganizationRole.OWNER)
    return organization_a, organization_b


async def _bind_organization(connection: AsyncConnection, organization_id: UUID) -> None:
    # The `true` makes the setting local to the current transaction, so it
    # can never leak into the next transaction on a pooled connection.
    await connection.execute(
        text("SELECT set_config('app.current_organization_id', :organization_id, true)"),
        {"organization_id": str(organization_id)},
    )


async def _bind_user(connection: AsyncConnection, user_id: UUID) -> None:
    # Like _bind_organization, for the caller: transaction-local, so it can
    # never leak into the next transaction on a pooled connection.
    await connection.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )


async def _visible_membership_organizations(connection: AsyncConnection) -> set[UUID]:
    # No WHERE clause on purpose: whatever comes back is what RLS allows.
    result = await connection.execute(text("SELECT organization_id FROM organization_memberships"))
    return set(result.scalars().all())


async def _visible_organizations(connection: AsyncConnection) -> set[UUID]:
    # No WHERE clause on purpose: whatever comes back is what RLS allows.
    result = await connection.execute(text("SELECT id FROM organizations"))
    return set(result.scalars().all())


async def _insert_membership(connection: AsyncConnection, organization_id: UUID, user_id: UUID) -> UUID:
    # A plain INSERT of an accepted member, as the runtime role. RETURNING
    # gives back the organization the row was written to; Postgres only
    # returns a row the SELECT policy also lets this transaction see.
    result = await connection.execute(
        text(
            "INSERT INTO organization_memberships "
            "(id, organization_id, user_id, role, invited_by_user_id, created_at, accepted_at) "
            "VALUES (:id, :organization_id, :user_id, 'member', :user_id, now(), now()) "
            "RETURNING organization_id"
        ),
        {"id": uuid4(), "organization_id": organization_id, "user_id": user_id},
    )
    # scalar_one() is typed Any; naming the type keeps mypy's
    # no-Any-return check satisfied.
    written_to: UUID = result.scalar_one()
    return written_to


async def test_an_unfiltered_select_returns_only_the_bound_organizations_memberships(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        visible = await _visible_membership_organizations(runtime_connection)

    # B's membership exists (seeded above), but a transaction bound to A
    # must not see it, even with no filter in the query.
    assert visible == {organization_a}
    assert organization_b not in visible


async def test_a_fresh_connection_with_no_organization_bound_sees_no_memberships(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # A confirmation test. This connection has never set the context, so
    # current_setting(..., true) returns NULL, NULL::uuid is NULL, and
    # organization_id = NULL is never true: RLS denies every row by default.
    await _two_organizations_with_a_member_each(it_session, it_user_service)

    async with runtime_connection.begin():
        visible = await _visible_membership_organizations(runtime_connection)

    assert visible == set()


async def test_a_reused_connection_with_no_organization_bound_sees_no_memberships_and_raises_nothing(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # The pooled-connection case. The first transaction binds A, as one
    # request would; the second runs on the same connection with nothing
    # bound, as the next request the pool hands it to might. When a
    # transaction-local setting ends, Postgres resets it to an empty string,
    # not back to NULL, so the policy then reads ''. ''::uuid is invalid
    # input, and without a guard the query errors out instead of returning
    # nothing.
    organization_a, _ = await _two_organizations_with_a_member_each(it_session, it_user_service)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
    async with runtime_connection.begin():
        visible = await _visible_membership_organizations(runtime_connection)

    assert visible == set()


async def test_a_context_that_is_not_a_uuid_fails_the_statement(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # A confirmation test. NULLIF only turns '' into NULL; any other value
    # that isn't a uuid must still fail the statement (SQLSTATE 22P02,
    # invalid text representation), never match rows or pass as "nothing
    # bound". The app only ever binds a real organization id, so such a
    # value means a bug upstream, and failing loudly makes it visible.
    await _two_organizations_with_a_member_each(it_session, it_user_service)

    # The first execute opens the transaction (SQLAlchemy begins one
    # automatically), so the setting is local to it. Only the SELECT goes
    # inside pytest.raises, so nothing else can raise the expected error.
    await runtime_connection.execute(
        text("SELECT set_config('app.current_organization_id', 'not-a-uuid', true)"),
    )
    with pytest.raises(DataError) as raised:
        await _visible_membership_organizations(runtime_connection)
    # The failed statement leaves the transaction aborted; end it.
    await runtime_connection.rollback()

    # SQLAlchemy types the driver's error (orig) as a plain BaseException,
    # which has no sqlstate attribute as far as mypy knows; getattr reads
    # the one psycopg sets.
    assert getattr(raised.value.orig, "sqlstate", None) == "22P02"


async def test_an_insert_into_the_bound_organization_succeeds(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # Isolation must not break the app's own writes: a transaction bound to
    # A may add a membership to A. With RLS on and no INSERT policy, Postgres
    # refuses every INSERT (default deny), so this needs a policy of its own.
    organization_a, _ = await _two_organizations_with_a_member_each(it_session, it_user_service)
    newcomer = await new_account(it_session, it_user_service)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        written_to = await _insert_membership(runtime_connection, organization_a, newcomer.user_id)

    assert written_to == organization_a


async def test_an_update_in_the_bound_organization_succeeds(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # Isolation must not break the app's own edits: a transaction bound to A
    # may change one of A's memberships (here, promote a member to admin).
    # With RLS on and no UPDATE policy, Postgres doesn't raise: the UPDATE
    # silently matches 0 rows. That's why the proof is RETURNING, never "no
    # error". An UPDATE that reads columns (its WHERE, its RETURNING) needs
    # the SELECT policy too, and A's memberships already pass that one.
    organization_a, _ = await _two_organizations_with_a_member_each(it_session, it_user_service)
    newcomer = await new_account(it_session, it_user_service)
    membership_id = await add_membership(it_session, organization_a, newcomer, OrganizationRole.MEMBER)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        result = await runtime_connection.execute(
            text("UPDATE organization_memberships SET role = 'admin' WHERE id = :id RETURNING role"),
            {"id": membership_id},
        )
        updated_roles = list(result.scalars().all())

    assert updated_roles == ["admin"]


async def test_a_delete_in_the_bound_organization_succeeds(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # Isolation must not break the app's own removals: a transaction bound to
    # A may delete one of A's memberships (a member leaving, or an invitation
    # being revoked). As with UPDATE, a missing DELETE policy raises nothing:
    # the DELETE silently matches 0 rows, so RETURNING is the proof. Its WHERE
    # and RETURNING read columns, so the SELECT policy applies too, and A's
    # memberships already pass it.
    organization_a, _ = await _two_organizations_with_a_member_each(it_session, it_user_service)
    newcomer = await new_account(it_session, it_user_service)
    membership_id = await add_membership(it_session, organization_a, newcomer, OrganizationRole.MEMBER)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        result = await runtime_connection.execute(
            text("DELETE FROM organization_memberships WHERE id = :id RETURNING id"),
            {"id": membership_id},
        )
        deleted_ids = list(result.scalars().all())

    assert deleted_ids == [membership_id]


async def test_an_insert_into_another_organization_is_refused(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # A confirmation test: the INSERT policy's WITH CHECK already exists. A
    # transaction bound to A tries to plant a membership in B. Unlike a read,
    # a write that breaks WITH CHECK isn't silently dropped: Postgres refuses
    # the whole statement with SQLSTATE 42501 (insufficient privilege), so a
    # bug can never put rows into someone else's organization.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)
    newcomer = await new_account(it_session, it_user_service)

    # The first execute opens the transaction, as in the non-uuid test above;
    # only the INSERT goes inside pytest.raises.
    #
    # No RETURNING on purpose. With RETURNING, Postgres would also check the
    # new row against the SELECT policy and raise 42501 from there, so the
    # test would pass even with no WITH CHECK at all. Without it, only the
    # INSERT policy's WITH CHECK can refuse the row.
    await _bind_organization(runtime_connection, organization_a)
    with pytest.raises(ProgrammingError) as raised:
        await runtime_connection.execute(
            text(
                "INSERT INTO organization_memberships "
                "(id, organization_id, user_id, role, invited_by_user_id, created_at, accepted_at) "
                "VALUES (:id, :organization_id, :user_id, 'member', :user_id, now(), now())"
            ),
            {"id": uuid4(), "organization_id": organization_b, "user_id": newcomer.user_id},
        )
    # The failed statement leaves the transaction aborted; end it.
    await runtime_connection.rollback()

    assert getattr(raised.value.orig, "sqlstate", None) == "42501"


async def test_an_update_moving_a_membership_into_another_organization_is_refused(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # A confirmation test: the UPDATE policy's WITH CHECK already exists. A
    # transaction bound to A tries to move A's membership into B. USING lets
    # the UPDATE touch A's row; WITH CHECK then vets the row it would write
    # back, which now says B, so Postgres refuses the statement with 42501.
    #
    # No WHERE and no RETURNING on purpose. An UPDATE that reads columns
    # (through either) is also checked against the SELECT policy, for the old
    # row and the new one, which would raise 42501 by itself. Without them,
    # only the UPDATE policy decides: USING picks A's rows (A has one), and
    # WITH CHECK refuses the move.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)

    await _bind_organization(runtime_connection, organization_a)
    with pytest.raises(ProgrammingError) as raised:
        await runtime_connection.execute(
            text("UPDATE organization_memberships SET organization_id = :organization_id"),
            {"organization_id": organization_b},
        )
    # The failed statement leaves the transaction aborted; end it.
    await runtime_connection.rollback()

    assert getattr(raised.value.orig, "sqlstate", None) == "42501"


async def test_an_update_never_touches_another_organizations_memberships(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # A confirmation test: the UPDATE policy's USING already exists. Bound to
    # A, a blanket UPDATE may change A's rows only; B's are skipped silently,
    # with no error, so the proof is reading the table afterwards as the
    # owner, who bypasses RLS and sees every row as it really is.
    #
    # No WHERE and no RETURNING on purpose: either would make the SELECT
    # policy filter B's row as well, hiding which policy did the work.
    # Without them, only the UPDATE policy's USING picks the rows.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        await runtime_connection.execute(text("UPDATE organization_memberships SET role = 'admin'"))

    # A fresh query on the owner's session, after the runtime transaction
    # committed: the whole table, organization by organization.
    result = await it_session.execute(text("SELECT organization_id, role FROM organization_memberships"))
    roles = {row.organization_id: row.role for row in result}

    # A's owner was changed, so the UPDATE really ran; B's owner wasn't.
    assert roles == {organization_a: "admin", organization_b: "owner"}


async def test_a_delete_never_removes_another_organizations_memberships(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # A confirmation test: the DELETE policy's USING already exists. Bound to
    # A, a blanket DELETE may remove A's rows only; B's are skipped silently,
    # with no error, so the proof is reading the table afterwards as the
    # owner, who bypasses RLS and sees every row as it really is.
    #
    # No WHERE and no RETURNING on purpose: either would make the SELECT
    # policy filter B's row as well, hiding which policy did the work.
    # Without them, only the DELETE policy's USING picks the rows.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        await runtime_connection.execute(text("DELETE FROM organization_memberships"))

    # A fresh query on the owner's session, after the runtime transaction
    # committed: which organizations still have memberships.
    result = await it_session.execute(text("SELECT organization_id FROM organization_memberships"))
    remaining = set(result.scalars().all())

    # A's membership is gone, so the DELETE really ran; B's is still there.
    assert remaining == {organization_b}
    assert organization_a not in remaining


async def test_a_user_with_no_organization_bound_sees_exactly_their_own_memberships(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # "My organizations", "my invitations" and the membership check itself
    # run before any organization can be bound, so a user must see their own
    # memberships in every organization, and nobody else's. Each owner's row
    # is the "nobody else's" part.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)
    member_of_both = await new_account(it_session, it_user_service)
    await add_membership(it_session, organization_a, member_of_both, OrganizationRole.MEMBER)
    await add_membership(it_session, organization_b, member_of_both, OrganizationRole.MEMBER)

    async with runtime_connection.begin():
        await _bind_user(runtime_connection, member_of_both.user_id)
        result = await runtime_connection.execute(
            text("SELECT organization_id, user_id FROM organization_memberships"),
        )
        visible = {(row.organization_id, row.user_id) for row in result}

    assert visible == {
        (organization_a, member_of_both.user_id),
        (organization_b, member_of_both.user_id),
    }


async def test_a_user_with_no_organization_bound_deletes_only_their_own_memberships(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # Declining an invitation (and leaving an organization) deletes the
    # user's own membership, and an invitee isn't a member, so no
    # organization can be bound. With only the user bound, a blanket DELETE
    # may remove that user's rows and nobody else's.
    #
    # No WHERE and no RETURNING on purpose: either would make the SELECT
    # policies filter rows as well. Without them, only the DELETE policies
    # pick the rows, and the owner's read afterwards shows what really went.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)
    member_of_both = await new_account(it_session, it_user_service)
    await add_membership(it_session, organization_a, member_of_both, OrganizationRole.MEMBER)
    await add_membership(it_session, organization_b, member_of_both, OrganizationRole.MEMBER)

    async with runtime_connection.begin():
        await _bind_user(runtime_connection, member_of_both.user_id)
        await runtime_connection.execute(text("DELETE FROM organization_memberships"))

    result = await it_session.execute(text("SELECT organization_id, user_id FROM organization_memberships"))
    remaining = [(row.organization_id, row.user_id) for row in result]
    members_rows = {organization for organization, user in remaining if user == member_of_both.user_id}
    other_rows = {organization for organization, user in remaining if user != member_of_both.user_id}

    # The user's own two memberships are gone; each owner's is still there.
    assert members_rows == set()
    assert other_rows == {organization_a, organization_b}


async def test_an_unfiltered_select_returns_only_the_bound_organization(
    it_session: AsyncSession,
    it_user_service: UserService,
    runtime_connection: AsyncConnection,
) -> None:
    # The organizations table itself, the same way as its memberships: a
    # transaction bound to A sees A's row and not B's, even with no filter
    # in the query.
    organization_a, organization_b = await _two_organizations_with_a_member_each(it_session, it_user_service)

    async with runtime_connection.begin():
        await _bind_organization(runtime_connection, organization_a)
        visible = await _visible_organizations(runtime_connection)

    assert visible == {organization_a}
    assert organization_b not in visible
