"""
Unit test for map_tables() taking the modules' table mappings from its caller
(docs/plans/16-modular-monolith.md, Step 4d): base's lower layers may not import
a module, so map_tables() maps base's own tables and then only the module
mappings it is given.

Mapping a domain class can't be undone inside a process, so, like
tests/base/characterisation/outbound/persistence_sqla/mappings/test_mapped_tables.py,
this file runs itself as a separate Python process and reads back what was
mapped, leaving the test process untouched.
"""

import json
import subprocess
import sys

# Importing these maps nothing: only calling map_tables() does.
from app.base.outbound.persistence_sqla.mappings.all import map_tables
from app.base.outbound.persistence_sqla.registry import mapper_registry

# base's own tables, sorted: Identity's users and sessions, the event outbox and API keys.
BASES_OWN_TABLES = ["api_keys", "auth_sessions", "event_outbox", "users"]


def _report_mapped_tables() -> None:
    # Runs only in the child process (see the __main__ block at the end): maps
    # base's tables with no module mappings, then writes the names of the tables
    # that were mapped to stdout as JSON.
    map_tables(module_mappings=())
    mapped = sorted(table.name for mapper in mapper_registry.mappers for table in mapper.tables)
    sys.stdout.write(json.dumps(mapped))


def test_with_no_module_mappings_only_bases_own_tables_are_mapped() -> None:
    # The feature-delete rule for tables (plan 16, user story 4): an app built
    # without Organizations maps none of its tables, and base's own still are.
    result = subprocess.run(
        [sys.executable, "-m", "tests.base.unit.outbound.persistence_sqla.mappings.test_all"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    assert json.loads(result.stdout) == BASES_OWN_TABLES


if __name__ == "__main__":
    # The child process the test above starts; pytest only imports this file, so it
    # never runs this block.
    _report_mapped_tables()
