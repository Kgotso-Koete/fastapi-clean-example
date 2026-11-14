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
from app.base.core.queries.list_users import ListUsers
from app.base.core.queries.ports.user_reader import UserReader
from app.base.main.cli.access_revoker import CliAccessRevoker
from app.base.main.cli.identity_provider import CliIdentityProvider
from app.base.main.config.settings import PasswordHasherSettings
from app.base.main.ioc.outbound import CeleryProvider, HasherThreadPoolProvider, PersistenceSqlaProvider
from app.base.main.modules import UNITS, Unit, check_needs, collect_providers, collect_subscriptions
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
from app.base.outbound.auth_ctx.sqla_transaction_manager import AuthSqlaTransactionManager
from app.base.outbound.auth_ctx.sqla_tx_storage import AuthSessionSqlaTxStorage


class CliProvider(Provider):
    """
    The CLI's equivalent of CoreProvider (src/app/base/main/ioc/core.py) --
    deliberately independent of it (and of AuthProvider), for the same
    reason WorkerProvider (src/app/base/main/worker/provider.py) is independent:
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

    Deleting this file (and the rest of app.base.main.cli) would not require
    touching CoreProvider, AuthProvider, or any other pre-existing wiring.
    """

    scope = Scope.REQUEST

    def __init__(self, units: Sequence[Unit] = UNITS) -> None:
        # The registered units this CLI container is built with
        # (docs/plans/16-modular-monolith.md, "The registry"), as in CoreProvider:
        # get_cli_providers passes the same list it collects providers from, so the
        # handler registry below subscribes only handlers that are actually bound.
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

    # Event Ports -- see CoreProvider's identical comment: HybridEventDispatcher
    # reads each handler's own DISPATCH_MODE, so there's no branching here.
    event_dispatcher = provide(HybridEventDispatcher, provides=EventDispatcher)

    @provide(scope=Scope.REQUEST)
    async def provide_handler_registry(
        self,
        container: AsyncContainer,
    ) -> dict[type[DomainEvent], Sequence[EventHandler[Any]]]:
        """Pub/Sub registry: maps event types to their subscriber handlers."""
        # Built like CoreProvider's, from every registered unit's
        # CLI_SUBSCRIPTIONS: dishka builds each handler class listed there.
        return {
            event_type: [await container.get(handler_type) for handler_type in handler_types]
            for event_type, handler_types in collect_subscriptions(
                unit.CLI_SUBSCRIPTIONS for unit in self._units
            ).items()
        }


def get_cli_providers(units: Sequence[Unit] = UNITS) -> tuple[Provider, ...]:
    """
    Providers for the CLI process (see app.base.main.cli.container).
    HasherThreadPoolProvider/PersistenceSqlaProvider are reused as-is from
    main/ioc/outbound.py, same as WorkerProvider.get_worker_providers()
    already reuses them (neither needs a Request). CeleryProvider is reused
    too -- unlike the worker, the CLI's CreateUser command calls
    EventDispatcher.stage()/.dispatch() -> HybridEventDispatcher, which
    needs CeleryEnabled. AuthProvider/RequestProvider are deliberately
    excluded: the CLI has no HTTP request and never issues/reads a session.
    """
    # The registry's start-up check (docs/plans/16-modular-monolith.md, user
    # story 4): building the container is the first thing the CLI does, so a
    # unit whose need isn't registered stops it here, before it runs anything.
    check_needs(units)
    return (
        # The same units again: CliProvider subscribes handlers only from them,
        # so nothing is subscribed that collect_providers below didn't bind.
        CliProvider(units),
        HasherThreadPoolProvider(),
        PersistenceSqlaProvider(),
        CeleryProvider(),
        # Every registered unit's CLI providers, in registration order
        # (docs/plans/16-modular-monolith.md, "The registry").
        *collect_providers(unit.CLI_PROVIDERS for unit in units),
    )
