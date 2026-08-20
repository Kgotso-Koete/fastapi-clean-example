from app.main.celery_factory import build_celery_app


class TestBuildCeleryApp:
    """
    build_celery_app() is shared composition-root plumbing (see the
    docstring on the function itself for why it lives under `main` rather
    than `outbound/adapters`) -- a pure factory that, given plain config
    values, returns a fully-configured Celery application object. Both the
    web process (via CeleryProvider) and the worker process (main/worker/
    celery_app.py) call this same factory with their own values.
    """

    def test_wires_broker_and_result_backend(self) -> None:
        app = build_celery_app(
            app_name="test-app",
            broker_url="redis://redis:6379/0",
            result_backend_url="redis://redis:6379/1",
            default_queue="events",
            task_acks_late=True,
            worker_prefetch_multiplier=1,
        )

        # conf.broker_url/result_backend confirm the app will actually talk
        # to the Redis instance we configured it with.
        assert app.conf.broker_url == "redis://redis:6379/0"
        assert app.conf.result_backend == "redis://redis:6379/1"

    def test_uses_the_given_app_name_instead_of_a_hardcoded_one(self) -> None:
        # This repo is a template other people build their own projects on
        # top of -- the Celery app's own name must come from configuration
        # (the same AppSettings.SERVICE_NAME already used for the FastAPI
        # app's title), never a string baked into this factory.
        app = build_celery_app(
            app_name="someones-other-project",
            broker_url="redis://redis:6379/0",
            result_backend_url="redis://redis:6379/1",
            default_queue="events",
            task_acks_late=True,
            worker_prefetch_multiplier=1,
        )

        assert app.main == "someones-other-project"

    def test_uses_json_serialization_end_to_end(self) -> None:
        # JSON only (not Celery's default pickle) -- pickle can execute
        # arbitrary code on deserialization, which is not something we want
        # a message coming off a queue to be able to do.
        app = build_celery_app(
            app_name="test-app",
            broker_url="redis://redis:6379/0",
            result_backend_url="redis://redis:6379/1",
            default_queue="events",
            task_acks_late=True,
            worker_prefetch_multiplier=1,
        )

        assert app.conf.task_serializer == "json"
        assert app.conf.result_serializer == "json"
        assert app.conf.accept_content == ["json"]

    def test_applies_the_given_queue_acks_and_prefetch_settings(self) -> None:
        app = build_celery_app(
            app_name="test-app",
            broker_url="redis://redis:6379/0",
            result_backend_url="redis://redis:6379/1",
            default_queue="custom-queue",
            task_acks_late=False,
            worker_prefetch_multiplier=4,
        )

        assert app.conf.task_default_queue == "custom-queue"
        assert app.conf.task_acks_late is False
        assert app.conf.worker_prefetch_multiplier == 4

    def test_does_not_ignore_task_results(self) -> None:
        # Flower and the real-broker smoke test both need to be able to
        # query a task's outcome, so results must be kept (Celery's default
        # of task_ignore_result=False already matches this, but we assert
        # it explicitly since it's load-bearing for those two things).
        app = build_celery_app(
            app_name="test-app",
            broker_url="redis://redis:6379/0",
            result_backend_url="redis://redis:6379/1",
            default_queue="events",
            task_acks_late=True,
            worker_prefetch_multiplier=1,
        )

        assert app.conf.task_ignore_result is False
