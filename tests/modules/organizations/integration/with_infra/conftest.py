# Fixtures for Organizations' database tests.
#
# pytest gives a conftest.py's fixtures only to tests in the same folder or
# the folders inside it. These tests moved out of tests/base/integration/
# with_infra/, so they no longer sit under base's conftest files. Importing
# the fixtures here makes pytest offer them in this folder too. They are the
# same fixture functions, not copies, so a change to base's fixtures reaches
# these tests as well.
#
# allow_destructive is imported because it_db_clean asks for it by name.
# it_worker_runtime is automatic (autouse): importing it here makes it run
# around every test in this folder, as it does in base. it_public_app and
# it_public_client are the public API's app and client, used by
# test_organization_reads.py.
from tests.base.integration.conftest import allow_destructive
from tests.base.integration.with_infra.api_keys.conftest import it_public_app, it_public_client
from tests.base.integration.with_infra.conftest import (
    it_client,
    it_db_clean,
    it_di_overrides,
    it_fastapi_app,
    it_session,
    it_sessionmaker,
    it_units,
    it_user_service,
    it_worker_runtime,
)

# No code in this file uses these names; pytest finds fixtures by name. Without
# this list, ruff would report every import above as unused (F401).
__all__ = [
    "allow_destructive",
    "it_client",
    "it_db_clean",
    "it_di_overrides",
    "it_fastapi_app",
    "it_public_app",
    "it_public_client",
    "it_session",
    "it_sessionmaker",
    "it_units",
    "it_user_service",
    "it_worker_runtime",
]
