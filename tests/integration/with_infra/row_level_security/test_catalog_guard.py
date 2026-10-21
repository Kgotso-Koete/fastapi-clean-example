from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.main.config.loader import load_postgres_runtime_role_settings, load_postgres_settings
from app.outbound.persistence_sqla.row_level_security import (
    ALL_TABLE_PRIVILEGES,
    RUNTIME_GROUP,
    TABLE_RULES,
    TableKind,
)

# docs/plans/14-row-level-security.md, Step 2: the catalog guard.
#
# Every table in the database must be explicitly classified in TABLE_RULES
# (the security model in row_level_security.py), and each class decides the
# protection the table must have. A new table that isn't classified fails
# this file straight away, so nobody can add a table and forget to decide
# whether it holds organization data. A hand-kept list of "tables with an
# organization_id column" would drift: event_outbox already carries an
# organization's name in its payload without such a column.
#
# Migrations are generated from that same module (`make migration`), so
# these tests also catch a model change whose migration was never generated
# or applied: the database would no longer match what the module declares.
#
# These tests read Postgres's own catalog (pg_tables, pg_class, the
# information_schema views and has_table_privilege), so they check what the
# database really enforces, not what the code believes. They connect as the
# owner (postgres), who can see the whole catalog.

# Privileges app_runtime must never hold on any table, whatever the module
# declares: TRUNCATE ignores RLS entirely, REFERENCES lets a role probe
# other rows through foreign keys, TRIGGER lets it run code on them, and
# MAINTAIN (PostgreSQL 17+) allows LOCK TABLE, VACUUM and other whole-table
# commands that RLS can't limit (plan 14, finding 10).
_NEVER_GRANTED: Final = frozenset({"TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN"})

# The privileges Postgres also lets a role hold on single columns.
_COLUMN_PRIVILEGES: Final = ("SELECT", "INSERT", "UPDATE", "REFERENCES")

# Postgres's own privilege questions, asked about one role, one table and
# one privilege at a time. has_table_privilege sees only grants on a whole
# table; has_any_column_privilege is also true when a single column is
# granted. Adding "WITH GRANT OPTION" to the privilege asks whether the
# role may pass it on.
_HAS_TABLE_PRIVILEGE: Final = text("SELECT has_table_privilege(:role, :table, :privilege)")
_HAS_ANY_COLUMN_PRIVILEGE: Final = text("SELECT has_any_column_privilege(:role, :table, :privilege)")


@asynccontextmanager
async def _owner_connection() -> AsyncIterator[AsyncConnection]:
    # A short-lived engine of its own, logged in as the owner, so the whole
    # catalog is visible; disposed afterwards so no connection lingers.
    engine = create_async_engine(load_postgres_settings().dsn)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


def _organization_scoped_tables() -> list[str]:
    return sorted(table for table, rule in TABLE_RULES.items() if rule.kind is TableKind.ORGANIZATION_SCOPED)


async def _privileges_held(
    connection: AsyncConnection,
    question: TextClause,
    privileges: Iterable[str],
) -> dict[str, frozenset[str]]:
    # For every classified table, which of `privileges` Postgres says
    # app_runtime holds, asking one at a time. On purpose a different query
    # from the catalog reader the migration generator uses, so a bug there
    # can't hide itself here.
    held: dict[str, frozenset[str]] = {}
    for table in TABLE_RULES:
        granted: set[str] = set()
        for privilege in privileges:
            result = await connection.execute(
                question,
                {"role": RUNTIME_GROUP, "table": f"public.{table}", "privilege": privilege},
            )
            if result.scalar_one():
                granted.add(privilege)
        held[table] = frozenset(granted)
    return held


async def test_every_table_is_classified_and_every_classified_table_exists() -> None:
    # A confirmation test: true on day one. It exists to fail the day a
    # table is added (or dropped) without updating TABLE_RULES.
    async with _owner_connection() as connection:
        result = await connection.execute(
            text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"),
        )
        tables = set(result.scalars().all())

    # Two separate checks, so a failure says which way the list drifted.
    assert tables - set(TABLE_RULES) == set(), "unclassified tables"
    assert set(TABLE_RULES) - tables == set(), "classified tables that no longer exist"


async def test_every_table_with_an_organization_id_column_is_organization_scoped() -> None:
    # A confirmation test: a table that points at an organization almost
    # certainly holds that organization's data, so it can't be classified
    # as anything weaker.
    async with _owner_connection() as connection:
        result = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'organization_id'"
            )
        )
        tables_with_the_column = set(result.scalars().all())

    misclassified = {
        table
        for table in tables_with_the_column
        if table not in TABLE_RULES or TABLE_RULES[table].kind is not TableKind.ORGANIZATION_SCOPED
    }
    assert misclassified == set()


async def test_every_organization_scoped_table_has_row_level_security_enabled_and_not_forced() -> None:
    # relrowsecurity: RLS is on, so with no matching policy a non-bypassing
    # role sees nothing (default deny). relforcerowsecurity must be off
    # (Decision 2, option c): FORCE would hold the owner to the policies, but
    # the owner is a superuser in dev and test (who bypasses RLS anyway) and
    # an ordinary role on managed Postgres, so the owner's access would
    # differ depending on where the database runs. The app never connects
    # as the owner; it uses the runtime login, which RLS always applies to.
    organization_scoped = _organization_scoped_tables()
    async with _owner_connection() as connection:
        result = await connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
            ),
            {"tables": organization_scoped},
        )
        protection = {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in result}

    assert protection == dict.fromkeys(organization_scoped, (True, False))


async def test_app_runtime_holds_exactly_the_privileges_its_classification_allows() -> None:
    # has_table_privilege asks Postgres directly whether app_runtime can do
    # each thing on each table. Every privilege is checked, so a missing
    # grant breaks the app and an extra one (TRUNCATE above all) widens it:
    # either way the test fails and names the table.
    async with _owner_connection() as connection:
        held = await _privileges_held(connection, _HAS_TABLE_PRIVILEGE, ALL_TABLE_PRIVILEGES)

    assert held == {table: rule.runtime_privileges for table, rule in TABLE_RULES.items()}
    # Checked on the database itself, not on the module, so a mistake in
    # the module can't make this pass.
    never_granted_but_held = {table: privileges & _NEVER_GRANTED for table, privileges in held.items()}
    assert never_granted_but_held == dict.fromkeys(held, frozenset())


async def test_app_runtime_holds_no_column_level_grant_beyond_its_table_privileges() -> None:
    # A confirmation test (plan 14, finding 10). The test above can't see a
    # grant on a single column, yet one would matter: a stray
    # GRANT SELECT (payload) ON event_outbox would let the app read every
    # organization's staged events, and event_outbox has no RLS. Since
    # has_any_column_privilege is true for a whole-table grant or for any
    # one column, it must agree exactly with the declared table privileges.
    async with _owner_connection() as connection:
        held = await _privileges_held(connection, _HAS_ANY_COLUMN_PRIVILEGE, _COLUMN_PRIVILEGES)

    column_privileges = frozenset(_COLUMN_PRIVILEGES)
    assert held == {table: rule.runtime_privileges & column_privileges for table, rule in TABLE_RULES.items()}


async def test_app_runtime_holds_nothing_with_grant_option() -> None:
    # A confirmation test (plan 14, finding 10). A privilege held WITH GRANT
    # OPTION can be passed on: the runtime login, which inherits
    # app_runtime's privileges, could then grant them to any other role,
    # the staff roles included, outside the security model. Checked for
    # whole tables and for single columns.
    with_grant_option = [f"{privilege} WITH GRANT OPTION" for privilege in ALL_TABLE_PRIVILEGES]
    on_columns_with_grant_option = [f"{privilege} WITH GRANT OPTION" for privilege in _COLUMN_PRIVILEGES]
    async with _owner_connection() as connection:
        on_tables = await _privileges_held(connection, _HAS_TABLE_PRIVILEGE, with_grant_option)
        on_columns = await _privileges_held(connection, _HAS_ANY_COLUMN_PRIVILEGE, on_columns_with_grant_option)

    assert on_tables == dict.fromkeys(TABLE_RULES, frozenset())
    assert on_columns == dict.fromkeys(TABLE_RULES, frozenset())


async def test_the_runtime_roles_own_no_database_objects() -> None:
    # A confirmation test (plan 14, finding 10). PostgreSQL's GRANT page: a
    # role whose privileges are inherited "should not own any SQL objects",
    # because its members inherit the owner's rights too. Owning a table
    # would let the runtime login bypass that table's RLS (FORCE aside), and
    # owning a function would let it rewrite one. pg_shdepend records every
    # object's owner (deptype 'o'), whatever the kind of object, in every
    # database. Each role gets a row even with nothing owned, so a missing
    # role fails the test rather than passing it.
    roles = [RUNTIME_GROUP, load_postgres_runtime_role_settings().USER]
    async with _owner_connection() as connection:
        result = await connection.execute(
            text(
                "SELECT r.rolname, count(d.objid) AS owned "
                "FROM pg_catalog.pg_roles AS r "
                "LEFT JOIN pg_catalog.pg_shdepend AS d "
                "ON d.refclassid = 'pg_catalog.pg_authid'::regclass AND d.refobjid = r.oid AND d.deptype = 'o' "
                "WHERE r.rolname = ANY(:roles) "
                "GROUP BY r.rolname"
            ),
            {"roles": roles},
        )
        owned = {row.rolname: row.owned for row in result}

    assert owned == dict.fromkeys(roles, 0)


async def test_every_tables_policies_are_exactly_the_declared_ones() -> None:
    # Compared by name only, as the migration generator compares them
    # (Postgres rewrites a stored expression, so its text can't be compared).
    # A declared policy missing from the database means its migration was
    # never generated or applied; an extra one that nobody declared could be
    # a bypass, such as USING (true). Both fail here, naming the table.
    async with _owner_connection() as connection:
        result = await connection.execute(
            text("SELECT tablename, policyname FROM pg_catalog.pg_policies WHERE schemaname = 'public'"),
        )
        held: dict[str, set[str]] = {}
        for row in result:
            held.setdefault(row.tablename, set()).add(row.policyname)

    declared = {
        table: {policy.name for policy in rule.policies} for table, rule in TABLE_RULES.items() if rule.policies
    }
    assert held == declared


async def test_no_view_reads_an_organization_scoped_table_without_security_invoker() -> None:
    # A confirmation test: no views exist yet. A view normally runs with
    # its owner's rights, and the owner bypasses RLS, so a plain view over
    # an organization table would hand every organization's rows to anyone
    # allowed to read the view. security_invoker makes the view run with
    # the caller's rights instead, so the caller's policies apply.
    async with _owner_connection() as connection:
        result = await connection.execute(
            text(
                "SELECT DISTINCT u.view_name, c.reloptions "
                "FROM information_schema.view_table_usage AS u "
                "JOIN pg_catalog.pg_namespace AS n ON n.nspname = u.view_schema "
                "JOIN pg_catalog.pg_class AS c ON c.relname = u.view_name AND c.relnamespace = n.oid "
                "WHERE u.view_schema = 'public' AND u.table_name = ANY(:tables)"
            ),
            {"tables": _organization_scoped_tables()},
        )
        unsafe_views = [
            row.view_name
            for row in result
            if not {"security_invoker=true", "security_invoker=on"} & set(row.reloptions or [])
        ]

    assert unsafe_views == []
