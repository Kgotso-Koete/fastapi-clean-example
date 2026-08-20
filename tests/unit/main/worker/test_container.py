from collections.abc import Iterator

import pytest

from app.main.worker import container


@pytest.fixture(autouse=True)
def _reset_container() -> Iterator[None]:
    """
    container.py keeps the worker's single Dishka container in a
    module-level global (there's only ever one per worker process), so it
    would otherwise leak between tests -- every test starts and ends with
    no container set.
    """
    container.clear_worker_container()
    yield
    container.clear_worker_container()


class TestGetWorkerContainerBeforeInitialization:
    def test_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="not been initialized"):
            container.get_worker_container()


class TestSetAndGetWorkerContainer:
    """
    build_worker_container() itself needs real Postgres/Redis settings to
    run (it's exercised by the integration/smoke tests, not here) -- these
    tests instead cover the plain get/set/clear bookkeeping around it,
    using a stand-in object in place of a real Dishka AsyncContainer.
    """

    def test_get_returns_the_container_that_was_set(self) -> None:
        fake_container = object()

        container.set_worker_container(fake_container)  # type: ignore[arg-type]

        assert container.get_worker_container() is fake_container

    def test_clear_worker_container_resets_state(self) -> None:
        container.set_worker_container(object())  # type: ignore[arg-type]

        container.clear_worker_container()

        with pytest.raises(RuntimeError, match="not been initialized"):
            container.get_worker_container()
