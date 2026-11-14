"""
Characterisation test for the SQLAlchemy table mappings (docs/plans/16-modular-monolith.md,
Step 0). It records which tables map_tables() maps today, and to which domain class.
Every entrypoint calls map_tables() at start-up, and so does Alembic's env.py: a table
missing from it after a restructuring step would make `make migration` generate a
DROP TABLE. It is not a RED/GREEN cycle: it pins existing behaviour and passes on its
first run (O2: strict).
"""

import json
import subprocess
import sys

# Importing these maps nothing: only calling map_tables() does.
from app.base.main.modules import UNITS, collect_table_mappings
from app.base.outbound.persistence_sqla.mappings.all import map_tables
from app.base.outbound.persistence_sqla.registry import mapper_registry

# Table name -> the domain class mapped onto it. Class names rather than import paths,
# because Step 2 changes every import path and the tables must not change with it.
TODAYS_MAPPED_TABLES = {
    "users": "User",
    "auth_sessions": "AuthSession",
    "event_outbox": "OutboxMessage",
    "api_keys": "ApiKey",
    "organizations": "Organization",
    "organization_memberships": "OrganizationMembership",
}


def _report_mapped_tables() -> None:
    # Runs only in the child process (see the __main__ block at the end): maps the
    # tables, then writes what was mapped to stdout as JSON for the test to read.
    # The tables every entrypoint maps: base's and every registered unit's.
    map_tables(module_mappings=collect_table_mappings(unit.TABLE_MAPPINGS for unit in UNITS))
    report = {
        # mapper.tables: the tables a class is mapped onto (one each, today).
        "mapped": {
            table.name: mapper.class_.__qualname__ for mapper in mapper_registry.mappers for table in mapper.tables
        },
        "tables": sorted(mapper_registry.metadata.tables),
    }
    sys.stdout.write(json.dumps(report))


def test_map_tables_maps_exactly_todays_tables_to_todays_classes() -> None:
    # Mapping a domain class can't be undone inside a process, and no light test maps
    # the tables today. Calling map_tables() here would turn every domain class into a
    # mapped SQLAlchemy class for every unit test that runs after this one, quietly
    # changing their conditions. So this file runs itself as a separate Python process
    # (this interpreter, run again, as the CLI's real-subprocess tests in
    # tests/base/integration/with_infra/cli/test_list_users.py do), and the test process is
    # never touched.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.base.characterisation.outbound.persistence_sqla.mappings.test_mapped_tables",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    # Every table is mapped to the class it is mapped to today...
    assert report["mapped"] == TODAYS_MAPPED_TABLES
    # ...and MetaData holds no other table: none is defined without being mapped.
    assert report["tables"] == sorted(TODAYS_MAPPED_TABLES)


if __name__ == "__main__":
    # The child process the test above starts; pytest only imports this file, so it
    # never runs this block.
    _report_mapped_tables()
