from collections.abc import Iterable, Sequence

from dishka import Provider, Scope, provide

from app.base.main.ioc.outbound import HasherThreadPoolProvider, PersistenceSqlaProvider
from app.base.main.modules import UNITS, Unit, check_needs, collect_providers
from app.base.outbound.adapters.sqla_outbox_repository import SqlaOutboxRepository


class WorkerProvider(Provider):
    """
    Declares exactly what the registered event handlers need to run in a
    Celery worker process -- nothing more. Deliberately independent of
    CoreProvider/AuthProvider (the web process's providers), rather than
    reusing or splitting them: CoreProvider's CQRS commands need
    CurrentUserService, which needs a real Starlette Request through
    AuthService/CookieManager -- something a worker process fundamentally
    doesn't have. Dishka validates every declared provider's dependencies
    at container-build time, regardless of whether anything ever actually
    resolves them, so simply omitting a Request provider isn't enough --
    the worker's container must never declare anything that needs one.

    Its EmailSender binding comes from shared (src/app/shared/main/ioc/providers.py),
    which shared's main/module.py lists for the worker, as for the web app and the
    CLI. Deleting this file and app.base.main.worker entirely would not require
    touching CoreProvider, AuthProvider, or any other pre-existing wiring.
    """

    scope = Scope.APP

    # Bound by its own concrete type, not the core OutboxRepository
    # Protocol -- app.base.main.worker.outbox_drain_loop resolves it directly to
    # call get_pending()/mark_processed()/delete()/commit(), which aren't
    # part of that Protocol (see SqlaOutboxRepository's docstring).
    # REQUEST-scoped because it depends on the REQUEST-scoped AsyncSession
    # from PersistenceSqlaProvider below.
    outbox_repository = provide(SqlaOutboxRepository, scope=Scope.REQUEST)


def get_worker_providers(units: Sequence[Unit] = UNITS) -> Iterable[Provider]:
    """
    Providers for the Celery worker process (see app.base.main.worker.container).
    HasherThreadPoolProvider/PersistenceSqlaProvider are reused as-is from
    main/ioc/outbound.py (neither needs a Request, so both validate fine
    here) -- included now so a future DB-touching background handler (see
    the CreateInvoice illustration in docs/plans/3-celery-redis-events.md)
    has what it needs without further wiring
    changes. AuthProvider, RequestProvider, and CeleryProvider are
    deliberately excluded: the worker has no HTTP request, and it never
    dispatches events itself -- it only executes a handler resolved
    directly by dotted path (see app.base.main.worker.tasks._dispatch).
    """
    # The registry's start-up check (docs/plans/16-modular-monolith.md, user
    # story 4): building the container is the first thing the worker does, so a
    # unit whose need isn't registered stops it here, before it takes any task.
    check_needs(units)
    return (
        WorkerProvider(),
        HasherThreadPoolProvider(),
        PersistenceSqlaProvider(),
        # Every registered unit's worker providers, in registration order
        # (docs/plans/16-modular-monolith.md, "The registry").
        *collect_providers(unit.WORKER_PROVIDERS for unit in units),
    )
