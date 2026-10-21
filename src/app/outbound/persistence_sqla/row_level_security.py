"""The database security model, as readable code.

Which role may do what on each table, and which tables have Postgres
Row-Level Security (RLS), is declared here, next to the table mappings, never
hand-written into a migration (docs/plans/agents.md 4.7). Migrations are
generated from it: the planner below turns the declared model, plus what the
database holds right now, into the SQL that closes the gap and its exact
reverse, and the Alembic hook writes both into a new migration, the same way
autogenerate turns a mapping into CREATE TABLE.

See docs/plans/14-row-level-security.md ("Where the security model lives")
and the wiki page docs/wiki/content/core-patterns/row-level-security.md.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from alembic.operations import ops
from alembic.runtime.environment import ProcessRevisionDirectiveFn
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, text

# The no-login group role that every customer-facing grant (and, from Step 3,
# every policy) targets. The web app's login role is a member of it, created
# outside migrations by scripts/postgres/initdb/ (dev and test) or by ops.
RUNTIME_GROUP: Final = "app_runtime"

# Every privilege a table can carry. The reader asks about all of them, so an
# unexpected grant is always seen: above all TRUNCATE and MAINTAIN, which act
# on the whole table, so RLS can't limit them. MAINTAIN (PostgreSQL 17+)
# allows LOCK TABLE, VACUUM, CLUSTER, REINDEX and the statistics functions
# (plan 14, finding 10); older versions don't know it, and this template
# runs PostgreSQL 18.
ALL_TABLE_PRIVILEGES: Final = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)


class TableKind(StrEnum):
    """How a table's rows are owned, which decides how they're protected."""

    # Rows belong to one organization: Row-Level Security isolates them.
    ORGANIZATION_SCOPED = "organization-scoped"
    # Rows belong to one user; the application layer scopes them.
    USER_SCOPED = "user-scoped"
    # Platform-wide rows, protected by the application's own rules.
    GLOBAL = "global"
    # Plumbing and bookkeeping (an outbox, Alembic's version table).
    SYSTEM = "system"


class PolicyCommand(StrEnum):
    """The one command a policy covers. One policy per command, never FOR ALL
    (Supabase's advice), so each rule says which operation it was meant for."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    # Only ever read back from the database (a stray FOR ALL policy, like
    # the old spike's); the model itself never declares one.
    ALL = "ALL"


@dataclass(frozen=True, slots=True)
class Policy:
    """One Row-Level Security policy, declared by name.

    The planner compares policies by name only: Postgres rewrites an
    expression when it stores it, so the text can't be compared. Once
    committed, a policy is never edited in place; changing one means a new
    name (..._v2).
    """

    name: str
    command: PolicyCommand
    # Which existing rows the command may see or touch.
    using: str | None = None
    # Which new rows the command may write.
    with_check: str | None = None
    # False for a RESTRICTIVE policy. Only ever read back from the database;
    # every policy the model declares is permissive.
    permissive: bool = True
    # Every customer-facing policy targets app_runtime (plan 14, "Policies").
    roles: tuple[str, ...] = (RUNTIME_GROUP,)


@dataclass(frozen=True, slots=True)
class TableRule:
    """What the security model declares for one table."""

    kind: TableKind
    # The privileges app_runtime holds on the table: no more, no less.
    runtime_privileges: frozenset[str]
    # The table's Row-Level Security policies, created in this order.
    policies: tuple[Policy, ...] = ()

    @property
    def row_level_security(self) -> bool:
        # The one place that decides which tables get RLS: exactly the
        # organization-scoped ones.
        return self.kind is TableKind.ORGANIZATION_SCOPED


_READ_WRITE: Final = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})

# The organization the current transaction is bound to, read from the
# transaction-local setting (set_config(..., true)). Wrapped in (SELECT ...)
# so Postgres evaluates it once per statement instead of once per row
# (Supabase's measurements, plan 14 finding 6). NULLIF turns '' into NULL:
# once a transaction that bound an organization ends, Postgres leaves the
# setting as '' on that connection, not NULL, and ''::uuid would raise in
# the next transaction the pool runs there (plan 14 finding 1). NULL matches
# no row, so a transaction with nothing bound sees nothing.
_CURRENT_ORGANIZATION: Final = "(SELECT NULLIF(current_setting('app.current_organization_id', true), '')::uuid)"

# The user the current transaction acts for, read exactly like the
# organization above: once per statement, with '' (a setting left behind
# by an earlier transaction on the connection) treated as NULL, so a
# transaction with no user bound matches no row.
_CURRENT_USER: Final = "(SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid)"

# The security model: every table in the database, how its rows are owned,
# and exactly what app_runtime may do on it. Adding a table means adding it
# here, which forces the decision about how it's protected; the catalog
# guard fails until it is. A change here reaches the database only through
# `make migration`, which generates the SQL from it.
TABLE_RULES: Final[Mapping[str, TableRule]] = {
    # Rows belong to one organization: Row-Level Security isolates them.
    "organizations": TableRule(
        kind=TableKind.ORGANIZATION_SCOPED,
        runtime_privileges=_READ_WRITE,
        policies=(
            # The bound organization sees its own row. On this table the
            # organization is the row itself, so the column is id, not
            # organization_id. A user's own organizations (with none bound)
            # come with their own test.
            Policy(
                name="organizations_select",
                command=PolicyCommand.SELECT,
                using=f"id = {_CURRENT_ORGANIZATION}",
            ),
        ),
    ),
    "organization_memberships": TableRule(
        kind=TableKind.ORGANIZATION_SCOPED,
        runtime_privileges=_READ_WRITE,
        policies=(
            # Members of the bound organization see its memberships. The
            # user's own rows across organizations have their own policy,
            # below.
            Policy(
                name="organization_memberships_select",
                command=PolicyCommand.SELECT,
                using=f"organization_id = {_CURRENT_ORGANIZATION}",
            ),
            # A user sees their own memberships in every organization, with
            # or without one bound: "my organizations", "my invitations" and
            # the membership check itself all run before any organization can
            # be bound. A policy of its own rather than an OR in the one
            # above: Postgres ORs permissive policies together anyway, and
            # each rule stays readable on its own.
            Policy(
                name="organization_memberships_select_own",
                command=PolicyCommand.SELECT,
                using=f"user_id = {_CURRENT_USER}",
            ),
            # The bound organization may add memberships to itself. INSERT
            # has no existing row to filter, so only WITH CHECK applies: it
            # vets the new row, so a membership can only be written into the
            # bound organization.
            Policy(
                name="organization_memberships_insert",
                command=PolicyCommand.INSERT,
                with_check=f"organization_id = {_CURRENT_ORGANIZATION}",
            ),
            # The bound organization may change its own memberships (a role
            # change, for example; accepting an invitation is separate, see
            # Decision 6). USING picks which existing rows the UPDATE may
            # touch; WITH CHECK vets the row it writes back, so a membership
            # can never be moved into another organization.
            Policy(
                name="organization_memberships_update",
                command=PolicyCommand.UPDATE,
                using=f"organization_id = {_CURRENT_ORGANIZATION}",
                with_check=f"organization_id = {_CURRENT_ORGANIZATION}",
            ),
            # The bound organization may remove its own memberships (an admin
            # removing a member, an invitation revoked). A user's own rows
            # have their own policy, below. DELETE writes no
            # new row, so only USING applies: it picks which existing rows
            # may be deleted, and rows of any other organization are never
            # matched.
            Policy(
                name="organization_memberships_delete",
                command=PolicyCommand.DELETE,
                using=f"organization_id = {_CURRENT_ORGANIZATION}",
            ),
            # A user may delete their own memberships, with or without an
            # organization bound: declining an invitation (the invitee isn't
            # a member, so no organization can be bound) and leaving one.
            # Only USING applies, as for any DELETE. Which own rows may go
            # (never the last owner) stays the application layer's rule
            # (plan 14, Decision 4).
            Policy(
                name="organization_memberships_delete_own",
                command=PolicyCommand.DELETE,
                using=f"user_id = {_CURRENT_USER}",
            ),
        ),
    ),
    # Rows belong to one user; the application layer scopes them.
    "auth_sessions": TableRule(kind=TableKind.USER_SCOPED, runtime_privileges=_READ_WRITE),
    "api_keys": TableRule(kind=TableKind.USER_SCOPED, runtime_privileges=_READ_WRITE),
    # Platform-wide identity, protected by the application's admin rules.
    "users": TableRule(kind=TableKind.GLOBAL, runtime_privileges=_READ_WRITE),
    # Plumbing: the web app only stages events here (least privilege: INSERT
    # only), and the worker drains them as the owner. Not organization-scoped
    # by column, even though a payload can mention an organization.
    "event_outbox": TableRule(kind=TableKind.SYSTEM, runtime_privileges=frozenset({"INSERT"})),
    # Alembic's own bookkeeping. The app never touches it.
    "alembic_version": TableRule(kind=TableKind.SYSTEM, runtime_privileges=frozenset()),
}


@dataclass(frozen=True, slots=True)
class TableState:
    """What the database currently holds for one table."""

    runtime_privileges: frozenset[str]
    rls_enabled: bool
    rls_forced: bool
    # The policies the table has, with their stored definitions, so a
    # downgrade can recreate one the upgrade drops.
    policies: tuple[Policy, ...] = ()


@dataclass(frozen=True, slots=True)
class SecurityChanges:
    """The SQL a migration needs: what to apply, and how to undo it."""

    upgrade: tuple[str, ...]
    downgrade: tuple[str, ...]


# A table the database doesn't have yet (one the same migration is about to
# create) holds nothing at all.
_NOTHING: Final = TableState(runtime_privileges=frozenset(), rls_enabled=False, rls_forced=False)

# One change, paired with its exact undo: building both together means a
# downgrade can never drift out of step with its upgrade.
type _Step = tuple[str, str]


def plan_security_changes(rules: Mapping[str, TableRule], current: Mapping[str, TableState]) -> SecurityChanges:
    """The SQL that brings the database from `current` to what `rules` declare.

    Tables are handled in the order `rules` lists them, and privileges are
    sorted, so the same input always produces the same migration text.
    """
    steps: list[_Step] = []
    for table, rule in rules.items():
        state = current.get(table, _NOTHING)
        steps.extend(_privilege_steps(table, wanted=rule.runtime_privileges, held=state.runtime_privileges))
        steps.extend(_row_level_security_steps(table, wanted=rule.row_level_security, state=state))
        # After RLS, so a table never has policies while RLS is off; the
        # reversed undo then drops the policies before switching RLS off.
        steps.extend(_policy_steps(table, wanted=rule.policies, held=state.policies))

    return SecurityChanges(
        upgrade=tuple(change for change, _ in steps),
        # Every undo, in reverse order, so a downgrade unwinds step by step.
        downgrade=tuple(undo for _, undo in reversed(steps)),
    )


def _privilege_steps(table: str, *, wanted: frozenset[str], held: frozenset[str]) -> list[_Step]:
    grant = _grant_statement
    revoke = _revoke_statement
    steps: list[_Step] = []
    if missing := wanted - held:
        steps.append((grant(table, missing), revoke(table, missing)))
    # Anything extra is removed: above all TRUNCATE, which ignores RLS.
    if extra := held - wanted:
        steps.append((revoke(table, extra), grant(table, extra)))
    return steps


def _row_level_security_steps(table: str, *, wanted: bool, state: TableState) -> list[_Step]:
    # ENABLE: with no matching policy, a non-bypassing role sees and changes
    # nothing (default deny). Never FORCE (plan 14, Decision 2, option c):
    # FORCE holds the table's owner to the policies, but the owner is a
    # superuser in dev and test, who bypasses RLS anyway, and an ordinary
    # role on managed Postgres, so a forced table would behave differently
    # depending on where it's deployed. FORCE found on any table is removed,
    # whatever its kind. Superusers and BYPASSRLS roles always bypass.
    enable = (f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    no_force = (f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY", f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    steps: list[_Step] = []
    # NO FORCE comes first: switching a table off then unwinds in the reverse
    # of how it was switched on, and the downgrade puts FORCE back last.
    if state.rls_forced:
        steps.append(no_force)
    if wanted and not state.rls_enabled:
        steps.append(enable)
    elif not wanted and state.rls_enabled:
        steps.append((enable[1], enable[0]))
    return steps


def _policy_steps(table: str, *, wanted: tuple[Policy, ...], held: tuple[Policy, ...]) -> list[_Step]:
    # By name only (see Policy). Missing policies are created in the order
    # the model lists them; any the model doesn't declare are dropped, and
    # the definition read back from the database becomes their undo.
    held_names = {policy.name for policy in held}
    wanted_names = {policy.name for policy in wanted}
    steps = [
        (_create_policy_statement(table, policy), _drop_policy_statement(table, policy))
        for policy in wanted
        if policy.name not in held_names
    ]
    steps.extend(
        (_drop_policy_statement(table, policy), _create_policy_statement(table, policy))
        for policy in held
        if policy.name not in wanted_names
    )
    return steps


def _create_policy_statement(table: str, policy: Policy) -> str:
    # The model's own policies are always PERMISSIVE; RESTRICTIVE appears only
    # when recreating a stray policy read back from the database. USING and
    # WITH CHECK appear only when present, in that order.
    kind = "PERMISSIVE" if policy.permissive else "RESTRICTIVE"
    roles = ", ".join(policy.roles)
    parts = [f"CREATE POLICY {policy.name} ON {table} AS {kind} FOR {policy.command} TO {roles}"]
    if policy.using is not None:
        parts.append(f"USING ({policy.using})")
    if policy.with_check is not None:
        parts.append(f"WITH CHECK ({policy.with_check})")
    return " ".join(parts)


def _drop_policy_statement(table: str, policy: Policy) -> str:
    return f"DROP POLICY {policy.name} ON {table}"


def _grant_statement(table: str, privileges: frozenset[str]) -> str:
    return f"GRANT {_listed(privileges)} ON TABLE {table} TO {RUNTIME_GROUP}"


def _revoke_statement(table: str, privileges: frozenset[str]) -> str:
    return f"REVOKE {_listed(privileges)} ON TABLE {table} FROM {RUNTIME_GROUP}"


def _listed(privileges: frozenset[str]) -> str:
    return ", ".join(sorted(privileges))


# One round trip for every requested table, straight from Postgres's own
# catalog:
#   - relrowsecurity / relforcerowsecurity are the two RLS flags;
#   - has_table_privilege asks whether the role can do each thing, counting
#     grants to the role itself and to PUBLIC.
# Only real tables (relkind 'r' ordinary, 'p' partitioned) in the public
# schema are read, so a same-named object elsewhere can't be picked up. The
# role, the privilege list and the table names are all bound parameters.
_READ_CATALOG: Final = text(
    """
    SELECT
        c.relname AS table_name,
        c.relrowsecurity AS rls_enabled,
        c.relforcerowsecurity AS rls_forced,
        ARRAY(
            SELECT privilege
            FROM unnest(CAST(:privileges AS text[])) AS privilege
            WHERE has_table_privilege(CAST(:role AS name), c.oid, privilege)
        ) AS runtime_privileges
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
      AND c.relname = ANY(:tables)
    """
)

# Every policy on the requested tables, from Postgres's pg_policies view:
# the stored USING (qual) and WITH CHECK text, the command (cmd), the roles
# and whether it's PERMISSIVE or RESTRICTIVE. Public schema only, ordered by
# name so the result is stable.
_READ_POLICIES: Final = text(
    """
    SELECT tablename AS table_name, policyname AS name, permissive, roles, cmd, qual, with_check
    FROM pg_catalog.pg_policies
    WHERE schemaname = 'public' AND tablename = ANY(:tables)
    ORDER BY tablename, policyname
    """
)


def read_catalog_state(connection: Connection, tables: Iterable[str]) -> dict[str, TableState]:
    """What the database holds right now for each named table that exists.

    Its privileges for app_runtime, its two RLS flags, and its policies with
    their stored definitions (so the planner can recreate one it drops).
    Takes the plain (synchronous) connection Alembic hands its hooks. A name
    with no matching table is left out, so the planner treats it as having
    nothing yet. It only reads: nothing is changed.
    """
    # Used by both queries, so read the iterable once.
    names = list(tables)

    policies: dict[str, list[Policy]] = {}
    for row in connection.execute(_READ_POLICIES, {"tables": names}):
        policies.setdefault(row.table_name, []).append(
            Policy(
                name=row.name,
                command=PolicyCommand(row.cmd),
                using=row.qual,
                with_check=row.with_check,
                permissive=row.permissive == "PERMISSIVE",
                roles=tuple(row.roles),
            ),
        )

    rows = connection.execute(
        _READ_CATALOG,
        {"role": RUNTIME_GROUP, "privileges": list(ALL_TABLE_PRIVILEGES), "tables": names},
    )
    return {
        row.table_name: TableState(
            runtime_privileges=frozenset(row.runtime_privileges),
            rls_enabled=row.rls_enabled,
            rls_forced=row.rls_forced,
            policies=tuple(policies.get(row.table_name, ())),
        )
        for row in rows
    }


def security_revision_hook(rules: Mapping[str, TableRule]) -> ProcessRevisionDirectiveFn:
    """The hook that adds the security model's SQL to each autogenerated migration.

    env.py passes it to context.configure(process_revision_directives=...).
    When autogenerate has built the new migration in memory, Alembic calls
    it: it reads what the live database holds, plans the gap to `rules`,
    and adds that SQL to the migration before the file is written.
    """

    def add_security_changes(
        context: MigrationContext,
        _revision: object,
        directives: list[ops.MigrationScript],
    ) -> None:
        # Offline mode (--sql) only has a stand-in connection that prints
        # SQL, so there is no live state to compare against.
        if context.as_sql or context.connection is None:
            raise RuntimeError("The security model is planned against a live database; run autogenerate online.")
        changes = plan_security_changes(rules, read_catalog_state(context.connection, rules))
        # This project has one migration history, so Alembic hands over
        # one script with one upgrade and one downgrade.
        script = directives[0]
        # After the schema changes, so a new table exists before it's granted.
        script.upgrade_ops_list[0].ops.extend(ops.ExecuteSQLOp(statement) for statement in changes.upgrade)
        # Before the schema's own undo, so a grant is revoked before its
        # table is dropped.
        script.downgrade_ops_list[0].ops[:0] = [ops.ExecuteSQLOp(statement) for statement in changes.downgrade]

    return add_security_changes
