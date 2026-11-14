"""
shared's dishka provider (docs/plans/16-modular-monolith.md, Step 5 and "What goes
where"): base owns the EmailSender port, shared supplies the adapter, and base's
main/ binds the two by listing this provider for each entrypoint that sends email:
the web app, the CLI and the worker (the public API sends none). One class serves
all three, because the binding is the same at each.
"""

from dishka import Provider, Scope, provide

from app.base.core.common.ports.email_sender import EmailSender
from app.shared.main.config.settings import EmailSettings
from app.shared.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.shared.outbound.adapters.smtp_email_sender import SmtpEmailSender


class SharedEmailProvider(Provider):
    # One adapter for the whole process: built once, at start-up, from its settings.
    scope = Scope.APP

    @provide
    def provide_email_sender(self, settings: EmailSettings) -> EmailSender:
        # The console adapter writes each email to the log, for development; the
        # SMTP adapter sends it for real, through the configured mail server.
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
