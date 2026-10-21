from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.outbound.persistence_sqla.row_level_security import Policy, PolicyCommand, TableState, read_catalog_state

# docs/plans/14-row-level-security.md, Step 2b: the catalog reader.
#
# The planner (Step 2a) needs to know what the database holds right now. The
# reader asks Postgres directly, from its own catalog: which privileges the
# app_runtime group really has on each table, and whether Row-Level Security
# is enabled and forced. Alembic's autogenerate hook (Step 2c) calls it with
# the plain, synchronous connection Alembic hands its hooks, so these tests
# reach it the same way: through run_sync on an async connection, the bridge
# alembic/env.py already uses.
#
# Every test first sets an exact starting state inside its own transaction,
# so it doesn't depend on what the migrations have granted so far; the
# owner_connection fixture rolls all of it back afterwards.


async def _read(connection: AsyncConnection, tables: list[str]) -> dict[str, TableState]:
    return await connection.run_sync(lambda sync_connection: read_catalog_state(sync_connection, tables))


async def test_it_reads_exactly_the_privileges_app_runtime_holds(owner_connection: AsyncConnection) -> None:
    # Start from nothing on these three tables, then grant a known mix,
    # including TRUNCATE and MAINTAIN, so every kind of privilege is shown to
    # be read. MAINTAIN (PostgreSQL 17+) allows LOCK TABLE, VACUUM and other
    # whole-table commands that RLS can't limit (plan 14, finding 10).
    for table in ("api_keys", "users", "auth_sessions"):
        await owner_connection.execute(text(f"REVOKE ALL ON TABLE {table} FROM app_runtime"))
    await owner_connection.execute(text("GRANT SELECT, INSERT ON TABLE api_keys TO app_runtime"))
    await owner_connection.execute(text("GRANT TRUNCATE, MAINTAIN ON TABLE users TO app_runtime"))

    state = await _read(owner_connection, ["api_keys", "users", "auth_sessions"])

    assert state["api_keys"].runtime_privileges == frozenset({"SELECT", "INSERT"})
    assert state["users"].runtime_privileges == frozenset({"TRUNCATE", "MAINTAIN"})
    # Nothing granted reads as an empty set, not as a missing table.
    assert state["auth_sessions"].runtime_privileges == frozenset()


async def test_it_reads_the_enabled_and_forced_flags_separately(owner_connection: AsyncConnection) -> None:
    # Postgres allows each flag without the other. Giving the two tables
    # opposite flags catches a reader that mixes up which is which.
    for table in ("organizations", "organization_memberships"):
        await owner_connection.execute(text(f"REVOKE ALL ON TABLE {table} FROM app_runtime"))
    await owner_connection.execute(text("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY"))
    await owner_connection.execute(text("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY"))
    await owner_connection.execute(text("ALTER TABLE organization_memberships DISABLE ROW LEVEL SECURITY"))
    await owner_connection.execute(text("ALTER TABLE organization_memberships FORCE ROW LEVEL SECURITY"))

    state = await _read(owner_connection, ["organizations", "organization_memberships"])

    # Policies are left out: the organization tables carry real ones from
    # the Step 3 migration, and the reader's policy tests (on api_keys and
    # users) cover them.
    organizations = state["organizations"]
    memberships = state["organization_memberships"]
    assert (organizations.runtime_privileges, organizations.rls_enabled, organizations.rls_forced) == (
        frozenset(),
        True,
        False,
    )
    assert (memberships.runtime_privileges, memberships.rls_enabled, memberships.rls_forced) == (
        frozenset(),
        False,
        True,
    )


async def test_a_table_that_does_not_exist_is_left_out(owner_connection: AsyncConnection) -> None:
    # A table a migration is about to create isn't in the database yet. The
    # reader leaves it out, and the planner treats it as having nothing.
    state = await _read(owner_connection, ["organizations", "no_such_table"])

    assert "no_such_table" not in state
    assert "organizations" in state


# Step 3b: policies. These use api_keys and users, which never get real
# policies (they're user-scoped and global), so the policies the Step 3
# migration puts on the organization tables can't disturb them. Every
# CREATE POLICY here is rolled back by the owner_connection fixture.


async def test_it_reads_each_policy_with_its_stored_definition(owner_connection: AsyncConnection) -> None:
    # The planner drops a policy the model doesn't declare and recreates it
    # on downgrade, so the reader must return the definition Postgres
    # stored, not just the name. Ordered by name, so the result is stable.
    await owner_connection.execute(
        text("CREATE POLICY reader_select ON api_keys FOR SELECT TO app_runtime USING (true)"),
    )
    await owner_connection.execute(
        text("CREATE POLICY reader_insert ON api_keys FOR INSERT TO app_runtime WITH CHECK (true)"),
    )

    state = await _read(owner_connection, ["api_keys"])

    assert state["api_keys"].policies == (
        Policy(name="reader_insert", command=PolicyCommand.INSERT, with_check="true"),
        Policy(name="reader_select", command=PolicyCommand.SELECT, using="true"),
    )


async def test_it_reads_a_restrictive_for_all_policy_faithfully(owner_connection: AsyncConnection) -> None:
    # Our model never declares FOR ALL or RESTRICTIVE, but a stray policy
    # can be either (the old spike created a FOR ALL one), and a downgrade
    # must put back exactly what was there. TO PUBLIC reads back as "public".
    await owner_connection.execute(
        text("CREATE POLICY reader_all ON api_keys AS RESTRICTIVE FOR ALL TO PUBLIC USING (true)"),
    )

    state = await _read(owner_connection, ["api_keys"])

    assert state["api_keys"].policies == (
        Policy(name="reader_all", command=PolicyCommand.ALL, using="true", permissive=False, roles=("public",)),
    )


async def test_a_table_without_policies_reads_as_none(owner_connection: AsyncConnection) -> None:
    # A confirmation test: the empty case, pinned so a reader that returned
    # some other table's policies would fail here.
    state = await _read(owner_connection, ["users"])

    assert state["users"].policies == ()
