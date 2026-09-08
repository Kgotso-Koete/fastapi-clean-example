from collections.abc import Sequence
from typing import Any

from dishka import Provider, Scope, provide

from app.core.commands.activate_user import ActivateUser
from app.core.commands.create_user import CreateUser
from app.core.commands.deactivate_user import DeactivateUser
from app.core.commands.grant_admin import GrantAdmin
from app.core.commands.ports.flusher import Flusher
from app.core.commands.ports.outbox_repository import OutboxRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.user_tx_storage import UserTxStorage
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.commands.revoke_admin import RevokeAdmin
from app.core.commands.set_user_password import SetUserPassword
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.ports import AuthzUserFinder
from app.core.common.events.domain_event import DomainEvent
from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.events.user_registered import UserRegisteredEvent
from app.core.common.ports.access_revoker import AccessRevoker
from app.core.common.ports.email_sender import EmailSender
from app.core.common.ports.event_dispatcher import EventDispatcher
from app.core.common.ports.event_handler import EventHandler
from app.core.common.ports.identity_provider import IdentityProvider
from app.core.common.ports.password_hasher import PasswordHasher
from app.core.common.ports.user_finder import UserFinder
from app.core.common.services.user import UserService
from app.core.queries.list_users import ListUsers
from app.core.queries.ports.user_reader import UserReader
from app.main.cli.access_revoker import CliAccessRevoker
from app.main.cli.identity_provider import CliIdentityProvider
from app.main.config.settings import EmailSettings, PasswordHasherSettings
from app.main.ioc.outbound import CeleryProvider, HasherThreadPoolProvider, PersistenceSqlaProvider
from app.outbound.adapters.bcrypt_password_hasher import (
    BcryptPasswordHasher,
    HasherSemaphore,
    HasherThreadPoolExecutor,
)
from app.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.outbound.adapters.hybrid_event_dispatcher import HybridEventDispatcher
from app.outbound.adapters.smtp_email_sender import SmtpEmailSender
from app.outbound.adapters.sqla_flusher import SqlaFlusher
from app.outbound.adapters.sqla_outbox_repository import SqlaOutboxRepository
from app.outbound.adapters.sqla_transaction_manager import SqlaTransactionManager
from app.outbound.adapters.sqla_user_finder import SqlaUserFinder
from app.outbound.adapters.sqla_user_reader import SqlaUserReader
from app.outbound.adapters.sqla_user_tx_storage import SqlaUserTxStorage
from app.outbound.adapters.system_utc_timer import SystemUtcTimer
from app.outbound.auth_ctx.sqla_transaction_manager import AuthSqlaTransactionManager
from app.outbound.auth_ctx.sqla_tx_storage import AuthSessionSqlaTxStorage


class CliProvider(Provider):
    """
    The CLI's equivalent of CoreProvider (src/app/main/ioc/core.py) --
    deliberately independent of it (and of AuthProvider), for the same
    reason WorkerProvider (src/app/main/worker/provider.py) is independent:
    CoreProvider's identity_provider/access_revoker bindings both need a
    real Starlette Request through AuthService -> CookieManager, which a
    CLI invocation fundamentally doesn't have. Dishka validates a provider
    set's *whole* dependency graph at container-build time, so this can't
    be fixed by simply not calling the HTTP-bound pieces -- nothing
    declared here may need a Request at all. See docs/plans/6-inbound-cli.md
    for the full reasoning.

    Every binding below is a verbatim copy of CoreProvider's, except:
    - identity_provider is bound to CliIdentityProvider instead of
      AuthSessionIdentityProvider, plus the new user_finder addition it needs.
    - access_revoker is bound to CliAccessRevoker instead of
      AuthSessionAccessRevoker (which transitively needs a Request).

    Deleting this file (and the rest of app.main.cli) would not require
    touching CoreProvider, AuthProvider, or any other pre-existing wiring.
    """

    scope = Scope.REQUEST

    # Services
    user_service = provide(UserService, scope=Scope.APP)
    current_user_service = provide(CurrentUserService)

    # Common Ports
    @provide(scope=Scope.APP)
    def provide_password_hasher(
        self,
        settings: PasswordHasherSettings,
        executor: HasherThreadPoolExecutor,
        semaphore: HasherSemaphore,
    ) -> PasswordHasher:
        return BcryptPasswordHasher(
            pepper=settings.PEPPER.encode(),
            work_factor=settings.WORK_FACTOR,
            executor=executor,
            semaphore=semaphore,
            semaphore_wait_timeout_s=settings.SEMAPHORE_WAIT_TIMEOUT_S,
        )

    identity_provider = provide(CliIdentityProvider, provides=IdentityProvider)
    user_finder = provide(SqlaUserFinder, provides=UserFinder)
    authz_user_finder = provide(SqlaUserTxStorage, provides=AuthzUserFinder)
    auth_session_tx_storage = provide(AuthSessionSqlaTxStorage)
    auth_tx_manager = provide(AuthSqlaTransactionManager)
    access_revoker = provide(CliAccessRevoker, provides=AccessRevoker)

    # Commands Ports
    utc_timer = provide(SystemUtcTimer, provides=UtcTimer)
    user_tx_storage = provide(SqlaUserTxStorage, provides=UserTxStorage)
    flusher = provide(SqlaFlusher, provides=Flusher)
    tx_manager = provide(SqlaTransactionManager, provides=TransactionManager)
    outbox_repository = provide(SqlaOutboxRepository, provides=OutboxRepository)

    # Commands
    create_user = provide(CreateUser)
    set_user_password = provide(SetUserPassword)
    grant_admin = provide(GrantAdmin)
    revoke_admin = provide(RevokeAdmin)
    activate_user = provide(ActivateUser)
    deactivate_user = provide(DeactivateUser)

    # Query Ports
    user_reader = provide(SqlaUserReader, provides=UserReader)

    # Queries
    list_users = provide(ListUsers)

    # Event Handlers (Subscribers)
    send_welcome_email = provide(SendWelcomeEmail)

    # Event Ports -- see CoreProvider's identical comment: HybridEventDispatcher
    # reads each handler's own DISPATCH_MODE, so there's no branching here.
    event_dispatcher = provide(HybridEventDispatcher, provides=EventDispatcher)

    @provide(scope=Scope.APP)
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

    @provide(scope=Scope.REQUEST)
    def provide_handler_registry(
        self,
        send_welcome_email: SendWelcomeEmail,
    ) -> dict[type[DomainEvent], Sequence[EventHandler[Any]]]:
        """Pub/Sub registry: maps event types to their subscriber handlers."""
        return {
            UserRegisteredEvent: [send_welcome_email],
        }


def get_cli_providers() -> tuple[Provider, ...]:
    """
    Providers for the CLI process (see app.main.cli.container).
    HasherThreadPoolProvider/PersistenceSqlaProvider are reused as-is from
    main/ioc/outbound.py, same as WorkerProvider.get_worker_providers()
    already reuses them (neither needs a Request). CeleryProvider is reused
    too -- unlike the worker, the CLI's CreateUser command calls
    EventDispatcher.stage()/.dispatch() -> HybridEventDispatcher, which
    needs CeleryEnabled. AuthProvider/RequestProvider are deliberately
    excluded: the CLI has no HTTP request and never issues/reads a session.
    """
    return (
        CliProvider(),
        HasherThreadPoolProvider(),
        PersistenceSqlaProvider(),
        CeleryProvider(),
    )
