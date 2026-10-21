from typing import Final

import pytest
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext

from app.outbound.persistence_sqla.row_level_security import (
    Policy,
    PolicyCommand,
    TableKind,
    TableRule,
    TableState,
    plan_security_changes,
    security_revision_hook,
)

# docs/plans/14-row-level-security.md, Step 2a: the planner.
#
# The security model (which role may do what on each table, and which tables
# have Row-Level Security) lives in readable code, never hand-written into a
# migration (docs/plans/agents.md 4.7). The planner is the pure function that
# turns it into SQL: given the declared rules and what the database has right
# now, it returns the statements that close the gap (upgrade) and their exact
# reverse (downgrade). The Alembic hook (Step 2c) writes both into a generated
# migration, the same way autogenerate turns a mapping into CREATE TABLE.
#
# These tests use a small made-up model rather than the real one, so each
# expectation is easy to read: one table of each kind that matters.

_READ_WRITE: Final = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})

_RULES: Final = {
    # Organization data: read-write for the app, and Row-Level Security on.
    "notes": TableRule(kind=TableKind.ORGANIZATION_SCOPED, runtime_privileges=_READ_WRITE),
    # A user's own data: read-write, isolated by the application, no RLS.
    "sessions": TableRule(kind=TableKind.USER_SCOPED, runtime_privileges=_READ_WRITE),
    # Plumbing the app only appends to.
    "outbox": TableRule(kind=TableKind.SYSTEM, runtime_privileges=frozenset({"INSERT"})),
    # Bookkeeping the app never touches.
    "versions": TableRule(kind=TableKind.SYSTEM, runtime_privileges=frozenset()),
}

# A database that already holds exactly what _RULES declares.
_IN_SYNC: Final = {
    "notes": TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=False),
    "sessions": TableState(runtime_privileges=_READ_WRITE, rls_enabled=False, rls_forced=False),
    "outbox": TableState(runtime_privileges=frozenset({"INSERT"}), rls_enabled=False, rls_forced=False),
    "versions": TableState(runtime_privileges=frozenset(), rls_enabled=False, rls_forced=False),
}

# A database where nothing has been granted or switched on yet.
_NOTHING_YET: Final = {
    table: TableState(runtime_privileges=frozenset(), rls_enabled=False, rls_forced=False) for table in _RULES
}


def test_an_empty_database_gets_every_grant_and_rls_on_the_organization_scoped_tables() -> None:
    changes = plan_security_changes(_RULES, _NOTHING_YET)

    # Tables in the model's order; privileges sorted, so the same input always
    # produces the same migration text. Only "notes" is organization-scoped,
    # so only it gets RLS: ENABLE only (default deny for non-bypassing roles),
    # never FORCE (plan 14, Decision 2). "versions" gets nothing.
    assert changes.upgrade == (
        "GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE notes TO app_runtime",
        "ALTER TABLE notes ENABLE ROW LEVEL SECURITY",
        "GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE sessions TO app_runtime",
        "GRANT INSERT ON TABLE outbox TO app_runtime",
    )


def test_a_database_already_in_the_declared_state_gets_no_changes() -> None:
    # Otherwise every `make migration` would add the same statements again.
    changes = plan_security_changes(_RULES, _IN_SYNC)

    assert changes.upgrade == ()
    assert changes.downgrade == ()


def test_an_extra_privilege_is_revoked_and_the_downgrade_grants_it_back() -> None:
    # TRUNCATE ignores Row-Level Security entirely, so a stray grant of it is
    # exactly the kind of drift the generator must remove.
    current = {
        **_IN_SYNC,
        "notes": TableState(runtime_privileges=_READ_WRITE | {"TRUNCATE"}, rls_enabled=True, rls_forced=False),
    }

    changes = plan_security_changes(_RULES, current)

    assert changes.upgrade == ("REVOKE TRUNCATE ON TABLE notes FROM app_runtime",)
    assert changes.downgrade == ("GRANT TRUNCATE ON TABLE notes TO app_runtime",)


def test_the_downgrade_is_the_exact_reverse_of_the_upgrade() -> None:
    # Every statement inverted, in reverse order, so a downgrade unwinds the
    # upgrade step by step, exactly as Alembic's stairway test expects.
    changes = plan_security_changes(_RULES, _NOTHING_YET)

    assert changes.downgrade == (
        "REVOKE INSERT ON TABLE outbox FROM app_runtime",
        "REVOKE DELETE, INSERT, SELECT, UPDATE ON TABLE sessions FROM app_runtime",
        "ALTER TABLE notes DISABLE ROW LEVEL SECURITY",
        "REVOKE DELETE, INSERT, SELECT, UPDATE ON TABLE notes FROM app_runtime",
    )


def test_a_table_missing_from_the_database_counts_as_having_nothing() -> None:
    # A table that the same migration is about to create isn't in the
    # database yet, but it still needs its grants.
    current = {table: state for table, state in _IN_SYNC.items() if table != "outbox"}

    changes = plan_security_changes(_RULES, current)

    assert changes.upgrade == ("GRANT INSERT ON TABLE outbox TO app_runtime",)


def test_a_table_that_should_not_have_rls_gets_it_switched_off() -> None:
    # If a table is reclassified away from organization-scoped, its RLS goes
    # too: NO FORCE first, then DISABLE, the reverse of how it was switched on.
    current = {
        **_IN_SYNC,
        "sessions": TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=True),
    }

    changes = plan_security_changes(_RULES, current)

    assert changes.upgrade == (
        "ALTER TABLE sessions NO FORCE ROW LEVEL SECURITY",
        "ALTER TABLE sessions DISABLE ROW LEVEL SECURITY",
    )
    assert changes.downgrade == (
        "ALTER TABLE sessions ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE sessions FORCE ROW LEVEL SECURITY",
    )


def test_a_forced_organization_scoped_table_has_force_removed_and_keeps_rls() -> None:
    # Plan 14, Decision 2 (c): RLS is enabled, never forced. FORCE holds the
    # table's owner to the policies, but the owner is a superuser in dev and
    # test (superusers bypass RLS whatever FORCE says) and an ordinary role on
    # managed Postgres, so a forced table would treat the owner differently
    # depending on where it runs. A forced table is switched back; RLS stays on.
    current = {
        **_IN_SYNC,
        "notes": TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=True),
    }

    changes = plan_security_changes(_RULES, current)

    assert changes.upgrade == ("ALTER TABLE notes NO FORCE ROW LEVEL SECURITY",)
    assert changes.downgrade == ("ALTER TABLE notes FORCE ROW LEVEL SECURITY",)


# Step 3a: policies. A made-up policy for the "notes" table; its expression
# is only text to the planner, which never interprets it.
_NOTES_SELECT: Final = Policy(name="notes_select", command=PolicyCommand.SELECT, using="organization_id = 1")

# "notes" exactly as _IN_SYNC has it: granted, RLS on (never forced), no
# policies.
_NOTES_WITHOUT_POLICIES: Final = TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=False)


def test_a_declared_policy_the_database_lacks_is_created_after_rls_and_dropped_first_on_downgrade() -> None:
    # The policy comes after ENABLE, so the table is never left with
    # policies but RLS off. Undo runs in reverse: the policy goes first.
    rules = {
        "notes": TableRule(
            kind=TableKind.ORGANIZATION_SCOPED,
            runtime_privileges=_READ_WRITE,
            policies=(_NOTES_SELECT,),
        ),
    }

    changes = plan_security_changes(rules, {})

    assert changes.upgrade == (
        "GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE notes TO app_runtime",
        "ALTER TABLE notes ENABLE ROW LEVEL SECURITY",
        "CREATE POLICY notes_select ON notes AS PERMISSIVE FOR SELECT TO app_runtime USING (organization_id = 1)",
    )
    assert changes.downgrade[0] == "DROP POLICY notes_select ON notes"


def test_a_policy_already_present_by_name_gets_no_changes_even_if_its_stored_text_differs() -> None:
    # Postgres rewrites a policy's expression when it stores it (here, with
    # extra brackets), so comparing text would report drift on every
    # `make migration`. Policies are compared by name only; changing one
    # means a new name (plan 14, "Where the security model lives").
    rules = {
        "notes": TableRule(
            kind=TableKind.ORGANIZATION_SCOPED,
            runtime_privileges=_READ_WRITE,
            policies=(_NOTES_SELECT,),
        ),
    }
    stored = Policy(name="notes_select", command=PolicyCommand.SELECT, using="(organization_id = 1)")
    current = {
        "notes": TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=False, policies=(stored,)),
    }

    changes = plan_security_changes(rules, current)

    assert changes.upgrade == ()
    assert changes.downgrade == ()


def test_a_policy_the_model_does_not_declare_is_dropped_and_the_downgrade_recreates_it() -> None:
    # The same rule as for a stray privilege: whatever the model doesn't
    # declare is removed. A stray "everything is visible" policy is exactly
    # the kind of bypass the plan forbids. The downgrade rebuilds it from the
    # definition the catalog reader read back (Step 3b).
    stray = Policy(name="notes_everything", command=PolicyCommand.SELECT, using="true")
    rules = {"notes": TableRule(kind=TableKind.ORGANIZATION_SCOPED, runtime_privileges=_READ_WRITE)}
    current = {
        "notes": TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=False, policies=(stray,)),
    }

    changes = plan_security_changes(rules, current)

    assert changes.upgrade == ("DROP POLICY notes_everything ON notes",)
    assert changes.downgrade == (
        "CREATE POLICY notes_everything ON notes AS PERMISSIVE FOR SELECT TO app_runtime USING (true)",
    )


def test_update_and_insert_policies_render_only_the_clauses_they_declare() -> None:
    # USING picks the existing rows a command may touch; WITH CHECK decides
    # which new rows may be written. An UPDATE policy has both, in that
    # order; an INSERT policy can only have WITH CHECK (it has no existing
    # rows). Policies are created in the order the model lists them.
    update = Policy(
        name="notes_update",
        command=PolicyCommand.UPDATE,
        using="organization_id = 1",
        with_check="organization_id = 1",
    )
    insert = Policy(name="notes_insert", command=PolicyCommand.INSERT, with_check="organization_id = 1")
    rules = {
        "notes": TableRule(
            kind=TableKind.ORGANIZATION_SCOPED,
            runtime_privileges=_READ_WRITE,
            policies=(update, insert),
        ),
    }

    changes = plan_security_changes(rules, {"notes": _NOTES_WITHOUT_POLICIES})

    assert changes.upgrade == (
        (
            "CREATE POLICY notes_update ON notes AS PERMISSIVE FOR UPDATE TO app_runtime "
            "USING (organization_id = 1) WITH CHECK (organization_id = 1)"
        ),
        "CREATE POLICY notes_insert ON notes AS PERMISSIVE FOR INSERT TO app_runtime WITH CHECK (organization_id = 1)",
    )


def test_a_stray_restrictive_for_all_policy_is_recreated_exactly_on_downgrade() -> None:
    # Step 3b. A policy the reader found in the database, not one the model
    # declares: the model never declares FOR ALL or RESTRICTIVE, but the
    # downgrade must put back exactly what the upgrade removed.
    stray = Policy(name="notes_lockdown", command=PolicyCommand.ALL, using="true", permissive=False, roles=("public",))
    rules = {"notes": TableRule(kind=TableKind.ORGANIZATION_SCOPED, runtime_privileges=_READ_WRITE)}
    current = {
        "notes": TableState(runtime_privileges=_READ_WRITE, rls_enabled=True, rls_forced=False, policies=(stray,)),
    }

    changes = plan_security_changes(rules, current)

    assert changes.upgrade == ("DROP POLICY notes_lockdown ON notes",)
    assert changes.downgrade == ("CREATE POLICY notes_lockdown ON notes AS RESTRICTIVE FOR ALL TO public USING (true)",)


def test_the_revision_hook_refuses_to_plan_without_a_database_connection() -> None:
    # Step 2c. In offline mode Alembic has no database to read, so the hook
    # can't know what is already granted. Planning against nothing would
    # write grants that may already exist; a clear error is better.
    offline = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True})
    script = ops.MigrationScript(
        rev_id="test",
        upgrade_ops=ops.UpgradeOps(ops=[]),
        downgrade_ops=ops.DowngradeOps(ops=[]),
    )

    with pytest.raises(RuntimeError, match="live database"):
        security_revision_hook(_RULES)(offline, "test", [script])
