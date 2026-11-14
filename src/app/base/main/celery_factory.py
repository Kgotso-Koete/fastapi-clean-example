from celery import Celery


def build_celery_app(
    *,
    app_name: str,
    broker_url: str,
    result_backend_url: str,
    default_queue: str,
    task_acks_late: bool,
    worker_prefetch_multiplier: int,
) -> Celery:
    """
    Builds a configured Celery application object.

    Lives under `main`, not `outbound/adapters`, because it's shared
    composition-root plumbing, not a port implementation: nothing in
    `outbound` ever calls this function -- HybridEventDispatcher (the real
    EventDispatcher adapter) just takes an already-built `celery_app:
    Celery` constructor argument, agnostic to how it was built. Only two
    composition roots call this factory -- the web process's CeleryProvider
    (main/ioc/outbound.py) and the worker process (main/worker/celery_app.py)
    -- each with their own DI-resolved or directly-loaded values, ending up
    with their own Celery objects that agree only on the broker URL and the
    "app.events.dispatch_handler" task-name contract. They never share a
    Python object, since they're different OS processes.

    Takes plain values rather than settings objects on purpose, independent
    of layering: an explicit, minimal parameter list is easier to read and
    test than "pass me a settings blob and I'll dig out what I need."

    app_name is deliberately a required parameter, not a string baked into
    this function: this repo is a template other projects are built on top
    of, so nothing here should assume it's always called
    "fastapi_clean_example". Callers pass AppSettings.SERVICE_NAME -- the
    same value already used for the FastAPI app's own title -- so both
    processes agree on one configurable identity.
    """
    app = Celery(app_name, broker=broker_url, backend=result_backend_url)
    app.conf.update(
        # JSON only, never Celery's default pickle -- pickle can execute
        # arbitrary code on deserialization, which a message coming off a
        # queue should never be able to do.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_default_queue=default_queue,
        # acks_late=True means a task is only acknowledged (removed from
        # the queue) after it finishes, not the moment a worker picks it
        # up -- so a worker crash mid-task leaves the task to be retried
        # by another worker, instead of silently dropping it.
        task_acks_late=task_acks_late,
        worker_prefetch_multiplier=worker_prefetch_multiplier,
        # Flower (task monitoring dashboard) and the real-broker smoke test
        # both need to query a task's outcome via the result backend, so
        # results must not be discarded.
        task_ignore_result=False,
    )
    return app
