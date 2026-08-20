from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Final, cast

import asgi_lifespan
import httpx2
import pytest
from celery import Celery
from dishka import Provider, Scope, provide
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.main.worker.tasks  # noqa: F401 -- side effect: registers dispatch_event_handler_task on _worker_celery_app below
from app.core.common.services.user import UserService
from app.main.config.settings import AppSettings
from app.main.run import make_app
from app.main.worker import (
    container as worker_container,
    loop_runtime,
)
from app.main.worker.celery_app import celery_app as _worker_celery_app
from app.outbound.persistence_sqla.registry import mapper_registry

LIFESPAN_MANAGER_STARTUP_TIMEOUT_S: Final[int] = 30


class _EagerCeleryProvider(Provider):
    """
    Test-only override for the web app's Celery dependency. In production,
    the web process (CeleryProvider) and the worker process each build
    their OWN independent Celery object, agreeing only on the broker URL
    and task-name contract -- but that means a task is only ever
    *registered* on the specific Celery object app.main.worker.tasks
    decorated it against. For a test to run the REAL task body (not just
    prove a message was published), HybridEventDispatcher's send_task()
    call needs to happen on THAT SAME object, with eager execution turned
    on, so it runs the task synchronously, in-process, with no broker
    round-trip needed.
    """

    scope = Scope.APP

    @provide
    def provide_celery_app(self) -> Celery:
        _worker_celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
        return _worker_celery_app


@pytest.fixture
def it_di_overrides() -> Sequence[Provider]:
    """
    Override in a test module to provide custom dependency overrides.
    Keep the same fixture signature.
    """
    return ()


@pytest.fixture
def it_fastapi_app(it_di_overrides: Sequence[Provider]) -> FastAPI:
    return make_app(
        _EagerCeleryProvider(),
        *it_di_overrides,
        app_settings=AppSettings(DEBUG_MODE=False),
    )


@pytest.fixture(autouse=True)
def it_worker_runtime(it_fastapi_app: FastAPI) -> Iterator[None]:
    """
    A "background"-mode event handler runs via a Celery task that resolves
    its handler from get_worker_container() and blocks on
    loop_runtime.run_coroutine() -- in a real worker process, both are
    primed once at startup by the worker_process_init signal. This fixture
    does the same priming for one test, pointing get_worker_container() at
    THIS test's own app container (so DI overrides like a SpyEmailSender
    apply to handlers resolved during dispatch, exactly as they apply to
    everything else in the test).
    """
    loop_runtime.start_loop()
    worker_container.set_worker_container(it_fastapi_app.state.dishka_container)
    yield
    worker_container.clear_worker_container()
    loop_runtime.stop_loop()


@pytest.fixture
async def it_client(it_fastapi_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    async with (
        asgi_lifespan.LifespanManager(
            it_fastapi_app,
            startup_timeout=LIFESPAN_MANAGER_STARTUP_TIMEOUT_S,
        ),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=it_fastapi_app),
            base_url="http://test",
        ) as client,
    ):
        yield client


@pytest.fixture
async def it_sessionmaker(
    it_client: httpx2.AsyncClient,
    it_fastapi_app: FastAPI,
) -> async_sessionmaker[AsyncSession]:
    container = it_fastapi_app.state.dishka_container
    session_maker = await container.get(async_sessionmaker[AsyncSession])
    return cast(async_sessionmaker[AsyncSession], session_maker)


@pytest.fixture
async def it_db_clean(
    allow_destructive: None,
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    table_names = [table.name for table in mapper_registry.metadata.sorted_tables if table.name != "alembic_version"]
    if not table_names:
        return

    sql = "TRUNCATE " + ", ".join(f'"{name}"' for name in table_names) + " RESTART IDENTITY CASCADE;"

    async with it_sessionmaker() as session:
        await session.execute(text(sql))
        await session.commit()


@pytest.fixture
async def it_session(
    it_db_clean: None,
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with it_sessionmaker() as session:
        yield session


@pytest.fixture
async def it_user_service(
    it_client: httpx2.AsyncClient,
    it_fastapi_app: FastAPI,
) -> UserService:
    container = it_fastapi_app.state.dishka_container
    user_service = await container.get(UserService)
    return cast(UserService, user_service)
