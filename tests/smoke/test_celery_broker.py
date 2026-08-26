import uuid
from datetime import UTC, datetime

from celery import Celery
from celery.result import AsyncResult
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from uuid_utils import compat as uuid_utils

from app.core.common.entities.types_ import UserId
from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.events.user_registered import UserRegisteredEvent
from app.main.celery_factory import build_celery_app
from app.main.config.loader import load_app_settings, load_celery_settings, load_postgres_settings, load_redis_settings
from app.outbound.adapters.event_serialization import dotted_path
from app.outbound.adapters.hybrid_event_dispatcher import DISPATCH_HANDLER_TASK_NAME
from app.outbound.adapters.outbox_message import OutboxMessage
from app.outbound.persistence_sqla.mappings.all import map_tables

SMOKE_TEST_TIMEOUT_S = 10
# Margin on top of one full drain-loop tick, to cover the broker round-trip
# and the handler's own run time -- not the tick wait itself.
DRAIN_SMOKE_TEST_MARGIN_S = 15


def _drain_smoke_test_timeout_s() -> float:
    """
    The real worker's own drain loop only ticks every
    CELERY_DRAIN_OUTBOX_INTERVAL_SECONDS rather than reacting instantly, so
    the wait budget must scale with whatever that setting actually is in
    this environment -- hardcoding a number that only fits the 3s default
    would time out for real, and correctly, whenever `.secrets` sets a
    larger interval (e.g. to cut worker DB polling in a low-traffic
    deployment). Worst case, the row is inserted right after a tick just
    ran, so the next one is a full interval away -- hence one full interval
    of wait, plus a fixed margin for the broker round-trip and handler
    run time on top.
    """
    celery_settings = load_celery_settings()
    return celery_settings.DRAIN_OUTBOX_INTERVAL_SECONDS + DRAIN_SMOKE_TEST_MARGIN_S


def _build_standalone_celery_app() -> Celery:
    """
    A Celery object independent of either the web app's or the worker's
    own -- this only needs to agree with them on the broker URL and the
    task-name contract, exactly like the real web and worker processes do.
    Shared by both tests below: one uses it to publish a task directly,
    the other only to construct an AsyncResult for a task it never
    publishes itself (see test_outbox_row_gets_drained_by_the_real_workers_own_loop).
    """
    app_settings = load_app_settings()
    redis_settings = load_redis_settings()
    celery_settings = load_celery_settings()
    return build_celery_app(
        app_name=app_settings.SERVICE_NAME,
        broker_url=redis_settings.url,
        result_backend_url=redis_settings.result_url,
        default_queue=celery_settings.TASK_DEFAULT_QUEUE,
        task_acks_late=celery_settings.TASK_ACKS_LATE,
        worker_prefetch_multiplier=celery_settings.WORKER_PREFETCH_MULTIPLIER,
    )


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
    producer = _build_standalone_celery_app()

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


def test_outbox_row_gets_drained_by_the_real_workers_own_loop() -> None:
    """
    Neither of this file's other paths actually proves the mechanism
    docs/plans/4-transactional-outbox.md exists for: the test above
    publishes straight to DISPATCH_HANDLER_TASK_NAME itself, bypassing
    the outbox entirely; tests/integration/with_infra's signup/create-user
    tests run Celery in eager mode with no separate worker process
    involved at all, and only assert a row was staged (processed_at IS
    NULL), never that anything actually drains it. Nothing anywhere
    proves that a real, separately-running `worker` container's own
    background loop (app.main.worker.outbox_drain_loop, started from
    worker_process_init -- see celery_app.py) actually starts up cleanly
    and notices a pending row on its own schedule, with no test or
    request code ever calling send_task() itself.

    This inserts one OutboxMessage row directly into the real Postgres
    test DB -- the SAME db_pg the docker-compose test stack's real
    `worker` container is also connected to -- and then does nothing
    except wait. Because the drain loop publishes under
    task_id=str(row.id) (see outbox_drain_loop._drain_outbox), knowing
    the row's id upfront is enough to construct the exact AsyncResult the
    real relay will eventually resolve; no polling of our own is needed.
    A worker-process startup regression exactly like this session's
    map_tables()-missing bug (which surfaced as an ArgumentError the
    instant the real drain loop tried to query the unmapped OutboxMessage
    class) would show up here as this test timing out, where it
    previously had to be caught by hand via docker logs/Adminer.
    """
    map_tables()
    engine = create_engine(load_postgres_settings().dsn)

    # Generated here, in this test, rather than read back off the ORM
    # object after commit -- Session() defaults to expire_on_commit=True,
    # so every attribute on `message` (including id_) would need a fresh
    # DB round-trip to read again once the session below closes, which a
    # detached instance can't do. Keeping the id in a plain local variable
    # sidesteps that entirely -- we generated it ourselves, so there's
    # nothing to read back.
    message_id = uuid_utils.uuid7()
    event = UserRegisteredEvent(
        occurred_at=datetime.now(UTC),
        user_id=UserId(uuid.uuid4()),
        username="drain-smoke-test-user",
        email="drain-smoke-test@example.com",
    )
    message = OutboxMessage(
        id_=message_id,
        event_type=dotted_path(UserRegisteredEvent),
        handler_type=dotted_path(SendWelcomeEmail),
        payload=event.to_payload(),
        created_at=datetime.now(UTC),
    )
    with Session(engine) as session:
        session.add(message)
        session.commit()

    async_result = AsyncResult(str(message_id), app=_build_standalone_celery_app())

    # Blocks until the real worker container's own drain loop -- not this
    # test -- notices the row and relays it.
    async_result.get(timeout=_drain_smoke_test_timeout_s())
    assert async_result.state == "SUCCESS"

    # What "closed end-to-end in Postgres" looks like depends on
    # CELERY_OUTBOX_RETAIN_AFTER_RELAY: retained rows are marked processed
    # in place, but the drain loop deletes the row entirely when it's off
    # (see outbox_drain_loop._drain_outbox) -- so a real, correctly
    # configured deployment with retention off would leave no row to find
    # here at all. Either outcome proves the same thing: the real worker's
    # drain loop actually reached and finished this row, not just that
    # Celery received a message under the right id.
    retain_after_relay = load_celery_settings().OUTBOX_RETAIN_AFTER_RELAY
    with Session(engine) as session:
        refreshed = session.get(OutboxMessage, message_id)
        if retain_after_relay:
            assert refreshed is not None
            assert refreshed.processed_at is not None
        else:
            assert refreshed is None

    engine.dispose()
