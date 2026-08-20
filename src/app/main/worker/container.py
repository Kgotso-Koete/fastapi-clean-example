from dishka import AsyncContainer, make_async_container

from app.main.config.loader import (
    load_email_settings,
    load_password_hasher_settings,
    load_postgres_settings,
    load_sqla_settings,
)
from app.main.config.settings import (
    EmailSettings,
    PasswordHasherSettings,
    PostgresSettings,
    SqlaSettings,
)
from app.main.worker.provider import get_worker_providers

# The one Dishka container for this worker *process* -- built once (via
# build_worker_container(), called from worker_process_init) and read many
# times (once per task, via get_worker_container()). Mirrors how the web
# process has exactly one container per FastAPI app instance.
_container: AsyncContainer | None = None


def build_worker_container() -> AsyncContainer:
    """
    Builds the APP-scope root Dishka container for this worker process.
    Must be called on the persistent worker loop (see
    app.main.worker.loop_runtime.start_loop) so any APP-scoped async
    resources it creates (e.g. the SQLAlchemy AsyncEngine) are bound to
    that same loop, not whatever loop happens to be current otherwise.
    """
    global _container
    _container = make_async_container(
        *get_worker_providers(),
        context={
            PostgresSettings: load_postgres_settings(),
            SqlaSettings: load_sqla_settings(),
            PasswordHasherSettings: load_password_hasher_settings(),
            EmailSettings: load_email_settings(),
        },
    )
    return _container


def get_worker_container() -> AsyncContainer:
    """Returns the container built by build_worker_container(). Raises if called before that."""
    if _container is None:
        raise RuntimeError("Worker container has not been initialized.")
    return _container


def set_worker_container(container: AsyncContainer) -> None:
    """
    Test-only escape hatch: lets tests point get_worker_container() at a
    container they control (e.g. the same one a test's FastAPI app is
    using), without going through the real Postgres/Redis-backed
    build_worker_container().
    """
    global _container
    _container = container


def clear_worker_container() -> None:
    """Resets the module back to its pre-init state. Used by test teardown, and by close_worker_container()."""
    global _container
    _container = None


async def close_worker_container() -> None:
    """Disposes the container's APP-scoped resources (DB engine, thread pools, ...) and clears the module state."""
    if _container is not None:
        await _container.close()
    clear_worker_container()
