from dishka import AsyncContainer, make_async_container

from app.main.cli.identity_provider import CliPassword, CliUsername
from app.main.cli.provider import get_cli_providers
from app.main.config.loader import (
    load_celery_settings,
    load_email_settings,
    load_password_hasher_settings,
    load_postgres_settings,
    load_sqla_settings,
)
from app.main.config.settings import (
    CelerySettings,
    EmailSettings,
    PasswordHasherSettings,
    PostgresSettings,
    SqlaSettings,
)

# The one Dishka container for this CLI *invocation* -- built once (via
# build_cli_container(), from main/cli/__main__.py) and read many times
# (once per subcommand, via get_cli_container()). Mirrors
# app.main.worker.container's module-level single-container pattern.
_container: AsyncContainer | None = None


def build_cli_container(username: str, password: str) -> AsyncContainer:
    """Builds the APP-scope root Dishka container for this CLI invocation."""
    global _container
    _container = make_async_container(
        *get_cli_providers(),
        context={
            CliUsername: CliUsername(username),
            CliPassword: CliPassword(password),
            PostgresSettings: load_postgres_settings(),
            SqlaSettings: load_sqla_settings(),
            PasswordHasherSettings: load_password_hasher_settings(),
            EmailSettings: load_email_settings(),
            CelerySettings: load_celery_settings(),
        },
    )
    return _container


def get_cli_container() -> AsyncContainer:
    """Returns the container built by build_cli_container(). Raises if called before that."""
    if _container is None:
        raise RuntimeError("CLI container has not been initialized.")
    return _container


def set_cli_container(container: AsyncContainer) -> None:
    """Test-only escape hatch: lets tests point get_cli_container() at a container they control."""
    global _container
    _container = container


def clear_cli_container() -> None:
    """Resets the module back to its pre-init state. Used by test teardown, and by close_cli_container()."""
    global _container
    _container = None


async def close_cli_container() -> None:
    """Disposes the container's APP-scoped resources (DB engine, thread pools, ...) and clears module state."""
    if _container is not None:
        await _container.close()
    clear_cli_container()
