from collections.abc import Sequence
from typing import Any

from dishka import Provider, Scope, provide

from app.core.commands.activate_user import ActivateUser
from app.core.commands.create_user import CreateUser
from app.core.commands.deactivate_user import DeactivateUser
from app.core.commands.grant_admin import GrantAdmin
from app.core.commands.ports.flusher import Flusher
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
from app.core.common.services.user import UserService
from app.core.queries.list_users import ListUsers
from app.core.queries.ports.user_reader import UserReader
from app.main.config.settings import EmailSettings, PasswordHasherSettings
from app.outbound.adapters.auth_session_access_revoker import AuthSessionAccessRevoker
from app.outbound.adapters.auth_session_identity_provider import AuthSessionIdentityProvider
from app.outbound.adapters.background_event_dispatcher import BackgroundEventDispatcher
from app.outbound.adapters.bcrypt_password_hasher import (
    BcryptPasswordHasher,
    HasherSemaphore,
    HasherThreadPoolExecutor,
)
from app.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.outbound.adapters.smtp_email_sender import SmtpEmailSender
from app.outbound.adapters.sqla_flusher import SqlaFlusher
from app.outbound.adapters.sqla_transaction_manager import SqlaTransactionManager
from app.outbound.adapters.sqla_user_reader import SqlaUserReader
from app.outbound.adapters.sqla_user_tx_storage import SqlaUserTxStorage
from app.outbound.adapters.system_utc_timer import SystemUtcTimer


class CoreProvider(Provider):
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

    identity_provider = provide(AuthSessionIdentityProvider, provides=IdentityProvider)
    authz_user_finder = provide(SqlaUserTxStorage, provides=AuthzUserFinder)
    access_revoker = provide(AuthSessionAccessRevoker, provides=AccessRevoker)

    # Commands Ports
    utc_timer = provide(SystemUtcTimer, provides=UtcTimer)
    user_tx_storage = provide(SqlaUserTxStorage, provides=UserTxStorage)
    flusher = provide(SqlaFlusher, provides=Flusher)
    tx_manager = provide(SqlaTransactionManager, provides=TransactionManager)

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

    # Event Ports
    event_dispatcher = provide(BackgroundEventDispatcher, provides=EventDispatcher)

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
        """
        Pub/Sub registry: maps event types to their subscriber handlers.
        To subscribe new code to an event, add the handler here.
        """
        return {
            UserRegisteredEvent: [send_welcome_email],
        }
