from collections.abc import Sequence

from dishka import Provider, Scope, provide

from app.base.core.commands.issue_api_key import IssueApiKey
from app.base.core.commands.ports.api_key_repository import ApiKeyRepository
from app.base.core.commands.ports.transaction_manager import TransactionManager
from app.base.core.commands.ports.utc_timer import UtcTimer
from app.base.core.commands.revoke_api_key import RevokeApiKey
from app.base.core.common.authorization.current_user_service import CurrentUserService
from app.base.core.common.authorization.ports import AuthzUserFinder
from app.base.core.common.ports.access_revoker import AccessRevoker
from app.base.core.common.ports.api_key_hasher import ApiKeyHasher
from app.base.core.common.ports.identity_provider import IdentityProvider
from app.base.core.common.ports.password_hasher import PasswordHasher
from app.base.core.common.ports.user_finder import UserFinder
from app.base.core.common.services.user import UserService
from app.base.core.queries.get_api_key_usage_stats import GetApiKeyUsageStats
from app.base.core.queries.get_own_profile import GetOwnProfile
from app.base.core.queries.list_api_keys import ListApiKeys
from app.base.core.queries.ports.api_key_reader import ApiKeyReader
from app.base.main.config.settings import ApiKeySettings, PasswordHasherSettings
from app.base.main.ioc.outbound import HasherThreadPoolProvider, PersistenceSqlaProvider, RequestProvider
from app.base.main.modules import UNITS, Unit, check_needs, collect_providers
from app.base.outbound.adapters.api_key_access_revoker import ApiKeyAccessRevoker
from app.base.outbound.adapters.api_key_identity_provider import ApiKeyIdentityProvider
from app.base.outbound.adapters.bcrypt_password_hasher import (
    BcryptPasswordHasher,
    HasherSemaphore,
    HasherThreadPoolExecutor,
)
from app.base.outbound.adapters.hmac_sha256_api_key_hasher import HmacSha256ApiKeyHasher
from app.base.outbound.adapters.sqla_api_key_reader import SqlaApiKeyReader
from app.base.outbound.adapters.sqla_api_key_repository import SqlaApiKeyRepository
from app.base.outbound.adapters.sqla_transaction_manager import SqlaTransactionManager
from app.base.outbound.adapters.sqla_user_finder import SqlaUserFinder
from app.base.outbound.adapters.sqla_user_tx_storage import SqlaUserTxStorage
from app.base.outbound.adapters.system_utc_timer import SystemUtcTimer


class PublicApiProvider(Provider):
    """
    The public API's equivalent of CoreProvider (src/app/base/main/ioc/core.py) --
    deliberately independent of it, for the same reason CliProvider
    (src/app/base/main/cli/provider.py) and WorkerProvider are independent:
    Dishka validates a provider set's whole dependency graph at
    container-build time, and this container's identity_provider/
    access_revoker bind to different concrete adapters than CoreProvider's,
    which can't coexist with CoreProvider's own bindings for the same
    Protocol in one container. See docs/plans/8-public-api-key-auth.md
    for the full reasoning.

    Named for the process/entrypoint it serves (the public API), matching
    CliProvider/WorkerProvider's own convention, not for the authentication
    mechanism (API keys) that process happens to use.

    Leaner than CoreProvider by design, not just a swap of two bindings:
    ApiKey never raises a domain event, so none of CoreProvider's
    event-dispatch machinery (EventDispatcher, SendWelcomeEmail, the
    handler registry, EmailSender, CeleryProvider) is declared here at all.

    Built up incrementally, one interactor per plan step, on top of the
    infra-only bindings Step 5 first declared. Deleting this file (and the
    rest of the public API) would not require touching CoreProvider,
    AuthProvider, or any other pre-existing wiring.
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

    identity_provider = provide(ApiKeyIdentityProvider, provides=IdentityProvider)
    access_revoker = provide(ApiKeyAccessRevoker, provides=AccessRevoker)
    authz_user_finder = provide(SqlaUserTxStorage, provides=AuthzUserFinder)
    user_finder = provide(SqlaUserFinder, provides=UserFinder)

    # Commands Ports
    utc_timer = provide(SystemUtcTimer, provides=UtcTimer)
    tx_manager = provide(SqlaTransactionManager, provides=TransactionManager)
    api_key_repository = provide(SqlaApiKeyRepository, provides=ApiKeyRepository)

    # Query Ports
    api_key_reader = provide(SqlaApiKeyReader, provides=ApiKeyReader)

    # ApiKey-specific
    @provide(scope=Scope.APP)
    def provide_api_key_hasher(self, settings: PasswordHasherSettings) -> ApiKeyHasher:
        # Reuses the existing PasswordHasherSettings.PEPPER -- this feature
        # needs zero new settings/env vars. See the plan's "key-hashing
        # decision" section for why HMAC-SHA256 rather than bcrypt, and
        # HmacSha256ApiKeyHasher's own docstring for the domain-separation
        # this pepper is put through before it's ever used to hash a key.
        return HmacSha256ApiKeyHasher(pepper=settings.PEPPER.encode())

    # Commands (Step 7+)
    @provide
    def provide_issue_api_key(
        self,
        user_finder: UserFinder,
        user_service: UserService,
        utc_timer: UtcTimer,
        api_key_hasher: ApiKeyHasher,
        api_key_repository: ApiKeyRepository,
        transaction_manager: TransactionManager,
        settings: ApiKeySettings,
    ) -> IssueApiKey:
        # A hand-written @provide, not bare provide(IssueApiKey), because
        # IssueApiKey's max_keys_per_user is a plain int -- dishka can't
        # auto-wire a bare int from ApiKeySettings the way it auto-wires
        # every other (Protocol-typed) constructor param above.
        return IssueApiKey(
            user_finder=user_finder,
            user_service=user_service,
            utc_timer=utc_timer,
            api_key_hasher=api_key_hasher,
            api_key_repository=api_key_repository,
            transaction_manager=transaction_manager,
            max_keys_per_user=settings.MAX_PER_USER,
        )

    # Queries (Step 8+)
    list_api_keys = provide(ListApiKeys)
    get_api_key_usage_stats = provide(GetApiKeyUsageStats)

    # Commands (Step 9+)
    revoke_api_key = provide(RevokeApiKey)

    # Entrypoint-agnostic -- also bound, unmodified, into CoreProvider.
    get_own_profile = provide(GetOwnProfile)


def get_public_api_providers(units: Sequence[Unit] = UNITS) -> tuple[Provider, ...]:
    """
    Providers for the public API process. HasherThreadPoolProvider/
    PersistenceSqlaProvider are reused as-is from main/ioc/outbound.py,
    same as CliProvider's own get_cli_providers() already reuses them --
    neither needs a Request. RequestProvider IS needed here (unlike the
    CLI/worker) -- ApiKeyIdentityProvider reads the X-API-Key header off a
    real Request, even though it needs none of AuthProvider's cookie/JWT/
    session machinery. AuthProvider itself and CeleryProvider are
    deliberately excluded: this container never issues a cookie session,
    and none of its interactors ever raise a domain event.
    """
    # The registry's start-up check (docs/plans/16-modular-monolith.md, user
    # story 4), as at the other entrypoints: a unit whose need isn't registered
    # stops the public API here, before it serves anything.
    check_needs(units)
    return (
        PublicApiProvider(),
        HasherThreadPoolProvider(),
        PersistenceSqlaProvider(),
        RequestProvider(),
        # Every registered unit's public API providers, in registration order
        # (plan 16, "The registry").
        *collect_providers(unit.PUBLIC_API_PROVIDERS for unit in units),
    )
