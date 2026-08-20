import uuid
from datetime import UTC, datetime

from celery.result import AsyncResult

from app.core.common.entities.types_ import UserId
from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.events.user_registered import UserRegisteredEvent
from app.main.celery_factory import build_celery_app
from app.main.config.loader import load_app_settings, load_celery_settings, load_redis_settings
from app.outbound.adapters.event_serialization import dotted_path
from app.outbound.adapters.hybrid_event_dispatcher import DISPATCH_HANDLER_TASK_NAME

SMOKE_TEST_TIMEOUT_S = 10


def test_dispatch_handler_task_runs_on_a_real_worker_via_redis() -> None:
    """
    Every other test touching Celery runs it in eager mode (see
    it_worker_runtime/_EagerCeleryProvider in
    tests/integration/with_infra/conftest.py) -- deliberately, to stay
    infra-light -- which means nothing else actually proves the real
    producer -> Redis -> worker wiring (queue name, JSON serializer,
    task-name contract) works. This test is that one exception: it builds
    its OWN Celery producer (no eager mode) pointed at the live `redis` +
    `worker` containers Docker Compose brings up for this test run (see
    the Makefile's test-docker-app target), publishes one real message,
    and waits for the real worker process to pick it up and run it.
    """
    app_settings = load_app_settings()
    redis_settings = load_redis_settings()
    celery_settings = load_celery_settings()

    # A separate Celery object from either the web app's or the worker's --
    # this test only needs to agree with them on the broker URL and the
    # task-name string, exactly like the real web and worker processes do.
    producer = build_celery_app(
        app_name=app_settings.SERVICE_NAME,
        broker_url=redis_settings.url,
        result_backend_url=redis_settings.result_url,
        default_queue=celery_settings.TASK_DEFAULT_QUEUE,
        task_acks_late=celery_settings.TASK_ACKS_LATE,
        worker_prefetch_multiplier=celery_settings.WORKER_PREFETCH_MULTIPLIER,
    )

    event = UserRegisteredEvent(
        occurred_at=datetime.now(UTC),
        user_id=UserId(uuid.uuid4()),
        username="smoke-test-user",
        email="smoke-test@example.com",
    )

    async_result: AsyncResult = producer.send_task(
        DISPATCH_HANDLER_TASK_NAME,
        kwargs={
            "event_type": dotted_path(UserRegisteredEvent),
            "handler_type": dotted_path(SendWelcomeEmail),
            "payload": event.to_payload(),
        },
    )

    # Blocks until the real worker container (running the `worker` command
    # from docker-entrypoint.sh) picks this message up off Redis and
    # finishes running it -- proving the actual broker/queue/serializer
    # contract, not just that a Python object was constructed correctly.
    async_result.get(timeout=SMOKE_TEST_TIMEOUT_S)

    assert async_result.state == "SUCCESS"
