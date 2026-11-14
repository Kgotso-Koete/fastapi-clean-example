from collections.abc import Sequence
from typing import Any

from dishka import AsyncContainer, Provider, Scope, provide

from app.base.core.commands.activate_user import ActivateUser
from app.base.core.commands.create_user import CreateUser
from app.base.core.commands.deactivate_user import DeactivateUser
from app.base.core.commands.grant_admin import GrantAdmin
from app.base.core.commands.ports.flusher import Flusher
from app.base.core.commands.ports.outbox_repository import OutboxRepository
from app.base.core.commands.ports.transaction_manager import TransactionManager
from app.base.core.commands.ports.user_tx_storage import UserTxStorage
from app.base.core.commands.ports.utc_timer import UtcTimer
from app.base.core.commands.revoke_admin import RevokeAdmin
from app.base.core.commands.set_user_password import SetUserPassword
from app.base.core.commands.update_user_profile import UpdateUserProfile
from app.base.core.common.authorization.current_user_service import CurrentUserService
from app.base.core.common.authorization.ports import AuthzUserFinder
from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.ports.access_revoker import AccessRevoker
from app.base.core.common.ports.event_dispatcher import EventDispatcher
from app.base.core.common.ports.event_handler import EventHandler
from app.base.core.common.ports.identity_provider import IdentityProvider
from app.base.core.common.ports.password_hasher import PasswordHasher
from app.base.core.common.ports.user_finder import UserFinder
from app.base.core.common.services.user import UserService
from app.base.core.queries.get_own_profile import GetOwnProfile
from app.base.core.queries.list_users import ListUsers
from app.base.core.queries.ports.user_reader import UserReader
from app.base.main.config.settings import PasswordHasherSettings
from app.base.main.modules import UNITS, Unit, collect_subscriptions
from app.base.outbound.adapters.auth_session_access_revoker import AuthSessionAccessRevoker
from app.base.outbound.adapters.auth_session_identity_provider import AuthSessionIdentityProvider
from app.base.outbound.adapters.bcrypt_password_hasher import (
    BcryptPasswordHasher,
    HasherSemaphore,
    HasherThreadPoolExecutor,
)
from app.base.outbound.adapters.hybrid_event_dispatcher import HybridEventDispatcher
from app.base.outbound.adapters.sqla_flusher import SqlaFlusher
from app.base.outbound.adapters.sqla_outbox_repository import SqlaOutboxRepository
from app.base.outbound.adapters.sqla_transaction_manager import SqlaTransactionManager
from app.base.outbound.adapters.sqla_user_finder import SqlaUserFinder
from app.base.outbound.adapters.sqla_user_reader import SqlaUserReader
from app.base.outbound.adapters.sqla_user_tx_storage import SqlaUserTxStorage
from app.base.outbound.adapters.system_utc_timer import SystemUtcTimer


class CoreProvider(Provider):
    scope = Scope.REQUEST

    def __init__(self, units: Sequence[Unit] = UNITS) -> None:
        # The registered units this container is built with
        # (docs/plans/16-modular-monolith.md, "The registry"). get_providers passes
        # the same list it collects providers from, so the handler registry below
        # subscribes only handlers that are actually bound: an app built without
        # a unit (the feature-delete test) subscribes none of that unit's handlers.
        super().__init__()
        self._units = units

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
    # Profile editing (docs/plans/10-profile-editing.md, Step 6).
    update_user_profile = provide(UpdateUserProfile)

    # Query Ports
    user_reader = provide(SqlaUserReader, provides=UserReader)

    # Queries
    list_users = provide(ListUsers)
    # Entrypoint-agnostic -- also bound, unmodified, into PublicApiProvider.
    # The concrete proof CurrentUserService abstracts over identity
    # mechanism: same class, same logic, two transports.
    get_own_profile = provide(GetOwnProfile)

    # UserFinder: base's own port and adapter. Organizations' InviteOrganizationMember
    # needs it (its web provider, src/app/modules/organizations/main/ioc/providers.py),
    # so the web app binds it here, as the public API does for IssueApiKey.
    user_finder = provide(SqlaUserFinder, provides=UserFinder)

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

    @provide(scope=Scope.REQUEST)
    async def provide_handler_registry(
        self,
        container: AsyncContainer,
    ) -> dict[type[DomainEvent], Sequence[EventHandler[Any]]]:
        """
        Pub/Sub registry: maps event types to their subscriber handlers.
        To subscribe new code to an event, list the handler in its unit's
        main/module.py (WEB_SUBSCRIPTIONS); src/app/base/main/modules.py
        combines every registered unit's list.
        """
        # collect_subscriptions gives handler classes; dishka builds each
        # instance here, from this request's container, with its dependencies.
        return {
            event_type: [await container.get(handler_type) for handler_type in handler_types]
            for event_type, handler_types in collect_subscriptions(
                unit.WEB_SUBSCRIPTIONS for unit in self._units
            ).items()
        }
