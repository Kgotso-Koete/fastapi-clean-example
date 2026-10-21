from typing import Final

import sqlalchemy as sa
from alembic.autogenerate import render_python_code
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.outbound.persistence_sqla.row_level_security import TableKind, TableRule, security_revision_hook

# docs/plans/14-row-level-security.md, Step 2c: the Alembic hook.
#
# When `make migration` runs autogenerate, Alembic builds the new migration
# in memory and hands it to env.py's process_revision_directives hook before
# writing the file. Ours reads the live database (Step 2b), plans the gap to
# the declared security model (Step 2a), and adds that SQL to the migration:
# upgrade statements after the schema changes, their reverse before them.
#
# These tests build the in-memory migration themselves, call the hook the
# way Alembic does (a MigrationContext on a plain, synchronous connection),
# and then check the text Alembic would write, rendered by Alembic's own
# render_python_code. A small made-up model keeps each expectation readable;
# the owner_connection fixture rolls back every grant the setup makes.

_SELECT_ONLY: Final = frozenset({"SELECT"})


def _run_hook(
    sync_connection: Connection,
    rules: dict[str, TableRule],
    upgrade: ops.UpgradeOps,
    downgrade: ops.DowngradeOps,
) -> None:
    # What Alembic hands the hook: its migration context and the one script
    # it is about to write.
    script = ops.MigrationScript(rev_id="test", upgrade_ops=upgrade, downgrade_ops=downgrade)
    hook = security_revision_hook(rules)
    hook(MigrationContext.configure(connection=sync_connection), "test", [script])


def _executed(container: ops.UpgradeOps | ops.DowngradeOps) -> list[str]:
    # Only the op.execute(...) lines of the rendered migration body.
    return [line.strip() for line in render_python_code(container).splitlines() if "op.execute(" in line]


async def test_it_writes_only_what_the_live_database_is_missing(owner_connection: AsyncConnection) -> None:
    # The database already grants SELECT; the model asks for SELECT and
    # INSERT. Only INSERT may appear, which proves the hook compared against
    # the real database rather than assuming an empty one.
    await owner_connection.execute(text("REVOKE ALL ON TABLE api_keys FROM app_runtime"))
    await owner_connection.execute(text("GRANT SELECT ON TABLE api_keys TO app_runtime"))
    rules = {"api_keys": TableRule(kind=TableKind.USER_SCOPED, runtime_privileges=frozenset({"SELECT", "INSERT"}))}
    upgrade, downgrade = ops.UpgradeOps(ops=[]), ops.DowngradeOps(ops=[])

    await owner_connection.run_sync(lambda sync_connection: _run_hook(sync_connection, rules, upgrade, downgrade))

    assert _executed(upgrade) == ["op.execute('GRANT INSERT ON TABLE api_keys TO app_runtime')"]
    assert _executed(downgrade) == ["op.execute('REVOKE INSERT ON TABLE api_keys FROM app_runtime')"]


async def test_a_table_created_in_the_same_migration_is_granted_after_it_is_created(
    owner_connection: AsyncConnection,
) -> None:
    # Autogenerate has already put the new table into the migration. A grant
    # on a table that doesn't exist yet would fail, and so would dropping a
    # table before revoking from it, so the order is the whole point.
    create = ops.CreateTableOp("widgets", [sa.Column("id", sa.Integer, primary_key=True)])
    upgrade, downgrade = ops.UpgradeOps(ops=[create]), ops.DowngradeOps(ops=[create.reverse()])
    rules = {"widgets": TableRule(kind=TableKind.USER_SCOPED, runtime_privileges=_SELECT_ONLY)}

    await owner_connection.run_sync(lambda sync_connection: _run_hook(sync_connection, rules, upgrade, downgrade))

    upgrade_text = render_python_code(upgrade)
    assert upgrade_text.index("op.create_table('widgets'") < upgrade_text.index(
        "op.execute('GRANT SELECT ON TABLE widgets TO app_runtime')"
    )
    downgrade_text = render_python_code(downgrade)
    assert downgrade_text.index("op.execute('REVOKE SELECT ON TABLE widgets FROM app_runtime')") < (
        downgrade_text.index("op.drop_table('widgets')")
    )
