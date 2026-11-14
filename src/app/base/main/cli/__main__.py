from app.base.main.cli.root_group import root_group
from app.base.main.modules import UNITS, collect_table_mappings
from app.base.outbound.persistence_sqla.mappings.all import map_tables

if __name__ == "__main__":
    """
    `python -m app.base.main.cli` -- this process's composition root. Mirrors
    main/run.py (web) and main/worker/celery_app.py (worker): map_tables()
    must run before anything queries a mapped class like User, since
    imperative mappings (see outbound/persistence_sqla/mappings) are wired
    up by that call, not merely by importing the class.
    """
    map_tables(module_mappings=collect_table_mappings(unit.TABLE_MAPPINGS for unit in UNITS))
    root_group()
