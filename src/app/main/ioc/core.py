from collections.abc import Sequence
from typing import Any

from dishka import Provider, Scope, provide

from app.core.commands.accept_organization_invitation import AcceptOrganizationInvitation
from app.core.commands.activate_user import ActivateUser
from app.core.commands.change_organization_member_role import ChangeOrganizationMemberRole
from app.core.commands.create_organization import CreateOrganization
from app.core.commands.create_user import CreateUser
from app.core.commands.deactivate_user import DeactivateUser
from app.core.commands.decline_organization_invitation import DeclineOrganizationInvitation
from app.core.commands.delete_organization import DeleteOrganization
from app.core.commands.grant_admin import GrantAdmin
from app.core.commands.invite_organization_member import InviteOrganizationMember
from app.core.commands.ports.flusher import Flusher
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.outbox_repository import OutboxRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.user_tx_storage import UserTxStorage
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.commands.remove_organization_member import RemoveOrganizationMember
from app.core.commands.revoke_admin import RevokeAdmin
from app.core.commands.set_user_password import SetUserPassword
from app.core.commands.update_organization import UpdateOrganization
from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.organization_ports import MembershipChecker
from app.core.common.authorization.ports import AuthzUserFinder
from app.core.common.events.domain_event import DomainEvent
from app.core.common.events.handlers.send_organization_invitation_email import SendOrganizationInvitationEmail
from app.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.core.common.events.organization_invitation_created import OrganizationInvitationCreatedEvent
from app.core.common.events.user_registered import UserRegisteredEvent
from app.core.common.ports.access_revoker import AccessRevoker
from app.core.common.ports.email_sender import EmailSender
from app.core.common.ports.event_dispatcher import EventDispatcher
from app.core.common.ports.event_handler import EventHandler
from app.core.common.ports.identity_provider import IdentityProvider
from app.core.common.ports.password_hasher import PasswordHasher
from app.core.common.ports.user_finder import UserFinder
from app.core.common.services.user import UserService
from app.core.queries.get_own_profile import GetOwnProfile
from app.core.queries.list_my_invitations import ListMyInvitations
from app.core.queries.list_my_organizations import ListMyOrganizations
from app.core.queries.list_organization_members import ListOrganizationMembers
from app.core.queries.list_users import ListUsers
from app.core.queries.ports.organization_reader import OrganizationReader
from app.core.queries.ports.user_reader import UserReader
from app.main.config.settings import EmailSettings, OrganizationSettings, PasswordHasherSettings
from app.outbound.adapters.auth_session_access_revoker import AuthSessionAccessRevoker
from app.outbound.adapters.auth_session_identity_provider import AuthSessionIdentityProvider
from app.outbound.adapters.bcrypt_password_hasher import (
    BcryptPasswordHasher,
    HasherSemaphore,
    HasherThreadPoolExecutor,
)
from app.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.outbound.adapters.hybrid_event_dispatcher import HybridEventDispatcher
from app.outbound.adapters.smtp_email_sender import SmtpEmailSender
from app.outbound.adapters.sqla_flusher import SqlaFlusher
from app.outbound.adapters.sqla_membership_checker import SqlaMembershipChecker
from app.outbound.adapters.sqla_organization_reader import SqlaOrganizationReader
from app.outbound.adapters.sqla_organization_repository import SqlaOrganizationRepository
from app.outbound.adapters.sqla_outbox_repository import SqlaOutboxRepository
from app.outbound.adapters.sqla_transaction_manager import SqlaTransactionManager
from app.outbound.adapters.sqla_user_finder import SqlaUserFinder
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
    # Entrypoint-agnostic -- also bound, unmodified, into PublicApiProvider.
    # The concrete proof CurrentUserService abstracts over identity
    # mechanism: same class, same logic, two transports.
    get_own_profile = provide(GetOwnProfile)

    # Organizations (docs/plans/9-organizations.md) -- appended as its own
    # block, growing one binding at a time as each use case's route lands.
    # MembershipChecker/CurrentOrganizationService/OrganizationReader join
    # here with the first route that actually needs them.
    organization_repository = provide(SqlaOrganizationRepository, provides=OrganizationRepository)
    create_organization = provide(CreateOrganization)
    # Invitations (Step 6): organization-scoped authorization, plus the
    # username lookup InviteOrganizationMember needs (bound here too now --
    # until this point only PublicApiProvider had UserFinder).
    membership_checker = provide(SqlaMembershipChecker, provides=MembershipChecker)
    current_organization_service = provide(CurrentOrganizationService)
    user_finder = provide(SqlaUserFinder, provides=UserFinder)
    accept_organization_invitation = provide(AcceptOrganizationInvitation)
    decline_organization_invitation = provide(DeclineOrganizationInvitation)
    # Membership management (Step 7).
    remove_organization_member = provide(RemoveOrganizationMember)
    change_organization_member_role = provide(ChangeOrganizationMemberRole)
    # The list queries (Step 8).
    organization_reader = provide(SqlaOrganizationReader, provides=OrganizationReader)
    list_my_organizations = provide(ListMyOrganizations)
    list_my_invitations = provide(ListMyInvitations)
    list_organization_members = provide(ListOrganizationMembers)
    # Deleting an organization (close-out, Step 11).
    delete_organization = provide(DeleteOrganization)
    # Renaming and describing an organization (close-out, Step 13).
    update_organization = provide(UpdateOrganization)

    @provide
    def provide_invite_organization_member(
        self,
        current_organization_service: CurrentOrganizationService,
        user_finder: UserFinder,
        organization_repository: OrganizationRepository,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
        settings: OrganizationSettings,
        event_dispatcher: EventDispatcher,
    ) -> InviteOrganizationMember:
        # Hand-written, like PublicApiProvider.provide_issue_api_key: the TTL
        # is a plain int, which dishka can't auto-wire from OrganizationSettings.
        return InviteOrganizationMember(
            current_organization_service=current_organization_service,
            user_finder=user_finder,
            organization_repository=organization_repository,
            utc_timer=utc_timer,
            transaction_manager=transaction_manager,
            invitation_ttl_days=settings.INVITATION_TTL_DAYS,
            event_dispatcher=event_dispatcher,
        )

    # Event Handlers (Subscribers)
    send_welcome_email = provide(SendWelcomeEmail)
    send_organization_invitation_email = provide(SendOrganizationInvitationEmail)

    # Event Ports
    # HybridEventDispatcher reads each handler's own DISPATCH_MODE (see the
    # EventHandler port) rather than a single app-wide setting -- so unlike
    # the old provide_event_dispatcher, there's no branching here: Dishka
    # resolves HybridEventDispatcher's constructor args (handler_registry
    # below, outbox_repository above, and CeleryEnabled from CeleryProvider
    # in main/ioc/outbound.py) by type on its own. It no longer needs the
    # Celery app object itself -- see docs/plans/4-transactional-outbox.md --
    # since it stages background handlers into the outbox instead of
    # publishing to Celery directly.
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
        send_organization_invitation_email: SendOrganizationInvitationEmail,
    ) -> dict[type[DomainEvent], Sequence[EventHandler[Any]]]:
        """
        Pub/Sub registry: maps event types to their subscriber handlers.
        To subscribe new code to an event, add the handler here.
        """
        return {
            UserRegisteredEvent: [send_welcome_email],
            OrganizationInvitationCreatedEvent: [send_organization_invitation_email],
        }
