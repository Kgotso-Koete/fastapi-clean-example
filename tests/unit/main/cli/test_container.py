from collections.abc import Iterator

import pytest

from app.main.cli import container


@pytest.fixture(autouse=True)
def _reset_container() -> Iterator[None]:
    """
    container.py keeps the CLI's single Dishka container in a module-level
    global (there's only ever one per CLI invocation), so it would otherwise
    leak between tests -- every test starts and ends with no container set.
    """
    container.clear_cli_container()
    yield
    container.clear_cli_container()


class TestGetCliContainerBeforeInitialization:
    def test_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="not been initialized"):
            container.get_cli_container()


class TestSetAndGetCliContainer:
    """
    build_cli_container() itself needs real Postgres settings and a real
    username/password to run (it's exercised by the integration tests, not
    here) -- these tests instead cover the plain get/set/clear bookkeeping
    around it, using a stand-in object in place of a real Dishka AsyncContainer.
    """

    def test_get_returns_the_container_that_was_set(self) -> None:
        fake_container = object()

        container.set_cli_container(fake_container)  # type: ignore[arg-type]

        assert container.get_cli_container() is fake_container

    def test_clear_cli_container_resets_state(self) -> None:
        container.set_cli_container(object())  # type: ignore[arg-type]

        container.clear_cli_container()

        with pytest.raises(RuntimeError, match="not been initialized"):
            container.get_cli_container()
