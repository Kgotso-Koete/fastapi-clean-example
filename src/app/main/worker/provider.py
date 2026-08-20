from collections.abc import Iterable

from dishka import Provider, Scope, provide

from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.ports.email_sender import EmailSender
from app.main.config.settings import EmailSettings
from app.main.ioc.outbound import HasherThreadPoolProvider, PersistenceSqlaProvider
from app.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.outbound.adapters.smtp_email_sender import SmtpEmailSender


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

    This does duplicate the email_sender wiring already in CoreProvider
    (see main/ioc/core.py) rather than share it. That's intentional: it
    keeps this class -- and the whole app.main.worker package -- a
    self-contained addition. Deleting this file and app.main.worker
    entirely would not require touching CoreProvider, AuthProvider, or any
    other pre-existing wiring.
    """

    scope = Scope.APP

    @provide
    def provide_email_sender(self, settings: EmailSettings) -> EmailSender:
        if settings.USE_CONSOLE:
            return ConsoleEmailSender()
        return SmtpEmailSender(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            from_email=settings.FROM_EMAIL,
            from_name=settings.FROM_NAME,
            use_tls=settings.SMTP_USE_TLS,
        )

    send_welcome_email = provide(SendWelcomeEmail, scope=Scope.REQUEST)


def get_worker_providers() -> Iterable[Provider]:
    """
    Providers for the Celery worker process (see app.main.worker.container).
    HasherThreadPoolProvider/PersistenceSqlaProvider are reused as-is from
    main/ioc/outbound.py (neither needs a Request, so both validate fine
    here) -- included now so a future DB-touching background handler (see
    the CreateInvoice illustration in docs/implementation-plans/
    celery-redis-events.md) has what it needs without further wiring
    changes. AuthProvider, RequestProvider, and CeleryProvider are
    deliberately excluded: the worker has no HTTP request, and it never
    dispatches events itself -- it only executes a handler resolved
    directly by dotted path (see app.main.worker.tasks._dispatch).
    """
    return (
        WorkerProvider(),
        HasherThreadPoolProvider(),
        PersistenceSqlaProvider(),
    )
