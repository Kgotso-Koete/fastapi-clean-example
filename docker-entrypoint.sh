#!/bin/bash
set -e

PORT=${2:-8000}

case "$1" in
    start)
        alembic upgrade head
        exec uvicorn app.main.run:make_app --factory --host 0.0.0.0 --port "$PORT" --reload
        ;;
    worker)
        # No separate `beat` command: the worker process starts its own
        # outbox-draining loop itself (see
        # src/app/main/worker/outbox_drain_loop.py, wired into
        # worker_process_init in celery_app.py) instead of a Celery Beat
        # schedule.
        exec celery -A app.main.worker.celery_app:celery_app worker \
            --loglevel=INFO \
            --queues="${CELERY_TASK_DEFAULT_QUEUE:-events}" \
            --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
        ;;
    pytest)
        alembic upgrade head
        shift
        exec pytest "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
