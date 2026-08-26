from app.main.celery_factory import build_celery_app
from app.main.config.loader import load_app_settings, load_celery_settings, load_redis_settings

# Loaded and built at import time, since Celery's own CLI entrypoint
# (`celery -A app.main.worker.celery_app:celery_app worker`) needs a real
# Celery object to exist the moment this module is imported -- before any
# Dishka container or event loop exists yet. This mirrors the web
# process's composition root (main/run.py), just without a request cycle.
_app_settings = load_app_settings()
_redis_settings = load_redis_settings()
_celery_settings = load_celery_settings()

celery_app = build_celery_app(
    app_name=_app_settings.SERVICE_NAME,
    broker_url=_redis_settings.url,
    result_backend_url=_redis_settings.result_url,
    default_queue=_celery_settings.TASK_DEFAULT_QUEUE,
    task_acks_late=_celery_settings.TASK_ACKS_LATE,
    worker_prefetch_multiplier=_celery_settings.WORKER_PREFETCH_MULTIPLIER,
)

# Imported here (not at the top of the file) because celery.signals and the
# worker/loop_runtime modules only need to exist once `celery_app` itself
# is already built -- and because tasks.py (imported at the very bottom)
# needs to import `celery_app` back from this module, which only works if
# the name is already assigned by the time that import runs.
from celery.signals import worker_process_init, worker_process_shutdown  # noqa: E402

from app.main.worker.container import build_worker_container, close_worker_container  # noqa: E402
from app.main.worker.loop_runtime import run_coroutine, start_loop, stop_loop  # noqa: E402
from app.outbound.persistence_sqla.mappings.all import map_tables  # noqa: E402


@worker_process_init.connect  # type: ignore[untyped-decorator]  # celery.signals ships without full type stubs
def _on_worker_process_init(**_kwargs: object) -> None:
    """
    Fires once when a Celery worker process starts, before it begins
    consuming any tasks. Mirrors what app.main.run's lifespan does for the
    web process: map_tables() must run before anything queries a mapped
    class like OutboxMessage, since imperative mappings (see
    outbound/persistence_sqla/mappings) are only wired up by that call, not
    merely by importing the class. Starts this process's one persistent
    event loop, builds its one Dishka container on that same loop, then
    starts the outbox drain loop on that same loop too -- there is no
    separate `beat` process; see outbox_drain_loop's own docstring for why.
    """
    map_tables()
    start_loop()
    run_coroutine(_async_init())
    outbox_drain_loop.start()


async def _async_init() -> None:
    build_worker_container()


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]  # celery.signals ships without full type stubs
def _on_worker_process_shutdown(**_kwargs: object) -> None:
    """
    Fires once when a Celery worker process is shutting down. Stops the
    drain loop, disposes the container, then stops the event loop.
    """
    outbox_drain_loop.stop()
    run_coroutine(close_worker_container())
    stop_loop()


# Imported purely for their side effects: tasks.py registers
# @celery_app.task(...) on the `celery_app` object above; outbox_drain_loop
# needs `celery_app` itself (to call send_task on) so it's imported here
# too rather than at the top of this file. Must stay the LAST lines in
# this module -- both modules import celery_app back from here, which
# only resolves once the assignment above has already run.
import app.main.worker.outbox_drain_loop as outbox_drain_loop  # noqa: E402
import app.main.worker.tasks  # noqa: E402,F401
