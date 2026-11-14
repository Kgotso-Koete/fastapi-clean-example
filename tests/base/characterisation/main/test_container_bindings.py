"""
Characterisation tests for the four dishka containers (docs/plans/16-modular-monolith.md,
Step 0). They record which concrete class every binding resolves to today, in the web
app, the public API, the CLI and the worker. dishka lets a later provider silently
replace an earlier binding of the same type, so a restructuring step that registers a
provider twice, or in a different order, would change behaviour without any error; these
tests catch it. They also record the bindings a container must NOT have (for example no
organization writes on the public API). They are not a RED/GREEN cycle: they pin
existing behaviour and pass on their first run (O2: strict).

Framework plumbing (the SQLAlchemy engine and sessions, the bcrypt thread pool, NewTypes
such as CeleryEnabled) is left out: its class says nothing about our wiring. The event
handler registry (which handlers each event is delivered to) has its own test at the end
of this file.
"""

from collections.abc import Sequence
from typing import Any, Literal

import pytest
from dishka import AsyncContainer, make_async_container
from dishka.exceptions import NoFactoryError
from starlette.requests import Request

from app.base.core.commands.activate_user import ActivateUser
from app.base.core.commands.create_user import CreateUser
from app.base.core.commands.deactivate_user import DeactivateUser
from app.base.core.commands.grant_admin import GrantAdmin
from app.base.core.commands.issue_api_key import IssueApiKey
from app.base.core.commands.ports.api_key_repository import ApiKeyRepository
from app.base.core.commands.ports.flusher import Flusher
from app.base.core.commands.ports.outbox_repository import OutboxRepository
from app.base.core.commands.ports.transaction_manager import TransactionManager
from app.base.core.commands.ports.user_tx_storage import UserTxStorage
from app.base.core.commands.ports.utc_timer import UtcTimer
from app.base.core.commands.revoke_admin import RevokeAdmin
from app.base.core.commands.revoke_api_key import RevokeApiKey
from app.base.core.commands.set_user_password import SetUserPassword
from app.base.core.commands.update_user_profile import UpdateUserProfile
from app.base.core.common.authorization.current_user_service import CurrentUserService
from app.base.core.common.authorization.ports import AuthzUserFinder
from app.base.core.common.events.domain_event import DomainEvent
from app.base.core.common.events.user_registered import UserRegisteredEvent
from app.base.core.common.ports.access_revoker import AccessRevoker
from app.base.core.common.ports.api_key_hasher import ApiKeyHasher
from app.base.core.common.ports.email_sender import EmailSender
from app.base.core.common.ports.event_dispatcher import EventDispatcher
from app.base.core.common.ports.event_handler import EventHandler
from app.base.core.common.ports.identity_provider import IdentityProvider
from app.base.core.common.ports.password_hasher import PasswordHasher
from app.base.core.common.ports.user_finder import UserFinder
from app.base.core.common.services.user import UserService
from app.base.core.queries.get_api_key_usage_stats import GetApiKeyUsageStats
from app.base.core.queries.get_own_profile import GetOwnProfile
from app.base.core.queries.list_api_keys import ListApiKeys
from app.base.core.queries.list_users import ListUsers
from app.base.core.queries.ports.api_key_reader import ApiKeyReader
from app.base.core.queries.ports.user_reader import UserReader
from app.base.main.cli.access_revoker import CliAccessRevoker
from app.base.main.cli.identity_provider import CliIdentityProvider, CliPassword, CliUsername
from app.base.main.cli.provider import get_cli_providers
from app.base.main.config.settings import (
    AlertSettings,
    ApiKeySettings,
    AppSettings,
    CelerySettings,
    CookieSettings,
    JwtSettings,
    PasswordHasherSettings,
    PostgresSettings,
    RedisSettings,
    SessionSettings,
    SqlaSettings,
)
from app.base.main.ioc.provider_registry import get_providers
from app.base.main.ioc.public_api import get_public_api_providers
from app.base.main.worker.provider import get_worker_providers
from app.base.outbound.adapters.api_key_access_revoker import ApiKeyAccessRevoker
from app.base.outbound.adapters.api_key_identity_provider import ApiKeyIdentityProvider
from app.base.outbound.adapters.auth_session_access_revoker import AuthSessionAccessRevoker
from app.base.outbound.adapters.auth_session_identity_provider import AuthSessionIdentityProvider
from app.base.outbound.adapters.bcrypt_password_hasher import BcryptPasswordHasher
from app.base.outbound.adapters.hmac_sha256_api_key_hasher import HmacSha256ApiKeyHasher
from app.base.outbound.adapters.hybrid_event_dispatcher import HybridEventDispatcher
from app.base.outbound.adapters.sqla_api_key_reader import SqlaApiKeyReader
from app.base.outbound.adapters.sqla_api_key_repository import SqlaApiKeyRepository
from app.base.outbound.adapters.sqla_flusher import SqlaFlusher
from app.base.outbound.adapters.sqla_outbox_repository import SqlaOutboxRepository
from app.base.outbound.adapters.sqla_transaction_manager import SqlaTransactionManager
from app.base.outbound.adapters.sqla_user_finder import SqlaUserFinder
from app.base.outbound.adapters.sqla_user_reader import SqlaUserReader
from app.base.outbound.adapters.sqla_user_tx_storage import SqlaUserTxStorage
from app.base.outbound.adapters.system_utc_timer import SystemUtcTimer
from app.base.outbound.auth_ctx.cookie_manager import CookieManager
from app.base.outbound.auth_ctx.handlers.change_password import ChangePassword
from app.base.outbound.auth_ctx.handlers.log_in import LogIn
from app.base.outbound.auth_ctx.handlers.log_out import LogOut
from app.base.outbound.auth_ctx.handlers.sign_up import SignUp
from app.base.outbound.auth_ctx.handlers.update_own_profile import UpdateOwnProfile
from app.base.outbound.auth_ctx.jwt_processor import JwtProcessor
from app.base.outbound.auth_ctx.service import AuthService
from app.base.outbound.auth_ctx.sqla_transaction_manager import AuthSqlaTransactionManager
from app.base.outbound.auth_ctx.sqla_tx_storage import AuthSessionSqlaTxStorage
from app.base.outbound.auth_ctx.sqla_user_tx_storage import AuthSqlaUserTxStorage
from app.base.outbound.auth_ctx.utc_timer import AuthSessionUtcTimer
from app.modules.notifications.core.common.events.handlers.send_organization_invitation_email import (
    SendOrganizationInvitationEmail,
)
from app.modules.notifications.core.common.events.handlers.send_welcome_email import SendWelcomeEmail
from app.modules.organizations.core.commands.accept_organization_invitation import AcceptOrganizationInvitation
from app.modules.organizations.core.commands.change_organization_member_role import ChangeOrganizationMemberRole
from app.modules.organizations.core.commands.create_organization import CreateOrganization
from app.modules.organizations.core.commands.decline_organization_invitation import DeclineOrganizationInvitation
from app.modules.organizations.core.commands.delete_organization import DeleteOrganization
from app.modules.organizations.core.commands.invite_organization_member import InviteOrganizationMember
from app.modules.organizations.core.commands.ports.organization_repository import OrganizationRepository
from app.modules.organizations.core.commands.remove_organization_member import RemoveOrganizationMember
from app.modules.organizations.core.commands.update_organization import UpdateOrganization
from app.modules.organizations.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.modules.organizations.core.common.authorization.organization_ports import MembershipChecker
from app.modules.organizations.core.common.events.organization_invitation_created import (
    OrganizationInvitationCreatedEvent,
)
from app.modules.organizations.core.queries.list_my_invitations import ListMyInvitations
from app.modules.organizations.core.queries.list_my_organizations import ListMyOrganizations
from app.modules.organizations.core.queries.list_organization_members import ListOrganizationMembers
from app.modules.organizations.core.queries.ports.organization_reader import OrganizationReader
from app.modules.organizations.main.config.settings import OrganizationSettings
from app.modules.organizations.outbound.adapters.sqla_membership_checker import SqlaMembershipChecker
from app.modules.organizations.outbound.adapters.sqla_organization_reader import SqlaOrganizationReader
from app.modules.organizations.outbound.adapters.sqla_organization_repository import SqlaOrganizationRepository
from app.shared.main.config.settings import EmailSettings
from app.shared.outbound.adapters.console_email_sender import ConsoleEmailSender
from app.shared.outbound.adapters.smtp_email_sender import SmtpEmailSender

# The four processes this codebase runs, each with its own container (plan 8).
Entrypoint = Literal["web", "public_api", "cli", "worker"]

# Every settings class is passed in literally, so a developer's .env can't change what
# a container resolves. Only the values that have no default are filled in; no
# connection is opened, because building an engine or a session never connects.
_POSTGRES = PostgresSettings(DB="db", HOST="host", PORT=5432, USER="user", PASSWORD="password")
_PASSWORD_HASHER = PasswordHasherSettings(PEPPER="p" * 32)
_SQLA = SqlaSettings()


def _make_container(entrypoint: Entrypoint, email_settings: EmailSettings) -> AsyncContainer:
    # Each branch uses the same provider list as the real entrypoint, and the same
    # context keys it passes (make_app in src/app/base/main/run.py, make_public_api_app in
    # src/app/base/main/run_public_api.py, build_cli_container and build_worker_container),
    # with literal values instead of the loaders.
    match entrypoint:
        case "web":
            return make_async_container(
                *get_providers(),
                context={
                    AppSettings: AppSettings(),
                    PostgresSettings: _POSTGRES,
                    SqlaSettings: _SQLA,
                    PasswordHasherSettings: _PASSWORD_HASHER,
                    JwtSettings: JwtSettings(SECRET="s" * 32),
                    SessionSettings: SessionSettings(),
                    CookieSettings: CookieSettings(),
                    EmailSettings: email_settings,
                    RedisSettings: RedisSettings(),
                    CelerySettings: CelerySettings(),
                    AlertSettings: AlertSettings(),
                    OrganizationSettings: OrganizationSettings(),
                },
            )
        case "public_api":
            return make_async_container(
                *get_public_api_providers(),
                context={
                    PasswordHasherSettings: _PASSWORD_HASHER,
                    PostgresSettings: _POSTGRES,
                    SqlaSettings: _SQLA,
                    ApiKeySettings: ApiKeySettings(),
                },
            )
        case "cli":
            return make_async_container(
                *get_cli_providers(),
                context={
                    CliUsername: CliUsername("cli-user"),
                    CliPassword: CliPassword("cli-password"),
                    PostgresSettings: _POSTGRES,
                    SqlaSettings: _SQLA,
                    PasswordHasherSettings: _PASSWORD_HASHER,
                    EmailSettings: email_settings,
                    CelerySettings: CelerySettings(),
                },
            )
        case "worker":
            return make_async_container(
                *get_worker_providers(),
                context={
                    PostgresSettings: _POSTGRES,
                    SqlaSettings: _SQLA,
                    PasswordHasherSettings: _PASSWORD_HASHER,
                    EmailSettings: email_settings,
                },
            )


async def _resolve(entrypoint: Entrypoint, key: type[Any], email_settings: EmailSettings | None = None) -> Any:
    # Builds a fresh container, resolves one binding inside a REQUEST scope (as a real
    # request, CLI command or Celery task would), then closes the container so its
    # APP-scoped resources, such as the bcrypt thread pool, shut down.
    container = _make_container(entrypoint, email_settings or EmailSettings())
    # The web app and the public API read the current HTTP request (the session cookie,
    # the X-API-Key header), so their REQUEST scope needs one. CookieManager and
    # ApiKeyIdentityProvider only store it, so an empty request is enough.
    context = {Request: Request({"type": "http"})} if entrypoint in {"web", "public_api"} else None
    try:
        async with container(context=context) as request_container:
            return await request_container.get(key)
    finally:
        await container.close()


# (entrypoint, what is asked for, the exact class it resolves to today). A port (a
# Protocol) maps to the adapter bound to it; a class bound by itself maps to itself.
BINDINGS: list[tuple[Entrypoint, type[Any], type[Any]]] = [
    # The web app: CoreProvider (src/app/base/main/ioc/core.py) and AuthProvider
    # (src/app/base/main/ioc/outbound.py).
    ("web", PasswordHasher, BcryptPasswordHasher),
    ("web", IdentityProvider, AuthSessionIdentityProvider),
    ("web", AuthzUserFinder, SqlaUserTxStorage),
    ("web", AccessRevoker, AuthSessionAccessRevoker),
    ("web", UtcTimer, SystemUtcTimer),
    ("web", UserTxStorage, SqlaUserTxStorage),
    ("web", Flusher, SqlaFlusher),
    ("web", TransactionManager, SqlaTransactionManager),
    ("web", OutboxRepository, SqlaOutboxRepository),
    ("web", UserReader, SqlaUserReader),
    ("web", OrganizationRepository, SqlaOrganizationRepository),
    ("web", MembershipChecker, SqlaMembershipChecker),
    ("web", UserFinder, SqlaUserFinder),
    ("web", OrganizationReader, SqlaOrganizationReader),
    ("web", EventDispatcher, HybridEventDispatcher),
    ("web", UserService, UserService),
    ("web", CurrentUserService, CurrentUserService),
    ("web", CurrentOrganizationService, CurrentOrganizationService),
    ("web", CreateUser, CreateUser),
    ("web", SetUserPassword, SetUserPassword),
    ("web", GrantAdmin, GrantAdmin),
    ("web", RevokeAdmin, RevokeAdmin),
    ("web", ActivateUser, ActivateUser),
    ("web", DeactivateUser, DeactivateUser),
    ("web", UpdateUserProfile, UpdateUserProfile),
    ("web", CreateOrganization, CreateOrganization),
    ("web", AcceptOrganizationInvitation, AcceptOrganizationInvitation),
    ("web", DeclineOrganizationInvitation, DeclineOrganizationInvitation),
    ("web", RemoveOrganizationMember, RemoveOrganizationMember),
    ("web", ChangeOrganizationMemberRole, ChangeOrganizationMemberRole),
    ("web", DeleteOrganization, DeleteOrganization),
    ("web", UpdateOrganization, UpdateOrganization),
    ("web", InviteOrganizationMember, InviteOrganizationMember),
    ("web", ListUsers, ListUsers),
    ("web", GetOwnProfile, GetOwnProfile),
    ("web", ListMyOrganizations, ListMyOrganizations),
    ("web", ListMyInvitations, ListMyInvitations),
    ("web", ListOrganizationMembers, ListOrganizationMembers),
    ("web", SendWelcomeEmail, SendWelcomeEmail),
    ("web", SendOrganizationInvitationEmail, SendOrganizationInvitationEmail),
    ("web", AuthService, AuthService),
    ("web", AuthSessionUtcTimer, AuthSessionUtcTimer),
    ("web", AuthSessionSqlaTxStorage, AuthSessionSqlaTxStorage),
    ("web", AuthSqlaTransactionManager, AuthSqlaTransactionManager),
    ("web", JwtProcessor, JwtProcessor),
    ("web", CookieManager, CookieManager),
    ("web", AuthSqlaUserTxStorage, AuthSqlaUserTxStorage),
    ("web", SignUp, SignUp),
    ("web", LogIn, LogIn),
    ("web", ChangePassword, ChangePassword),
    ("web", LogOut, LogOut),
    ("web", UpdateOwnProfile, UpdateOwnProfile),
    # The public API: PublicApiProvider (src/app/base/main/ioc/public_api.py).
    ("public_api", PasswordHasher, BcryptPasswordHasher),
    ("public_api", IdentityProvider, ApiKeyIdentityProvider),
    ("public_api", AccessRevoker, ApiKeyAccessRevoker),
    ("public_api", AuthzUserFinder, SqlaUserTxStorage),
    ("public_api", UserFinder, SqlaUserFinder),
    ("public_api", UtcTimer, SystemUtcTimer),
    ("public_api", TransactionManager, SqlaTransactionManager),
    ("public_api", ApiKeyRepository, SqlaApiKeyRepository),
    ("public_api", ApiKeyReader, SqlaApiKeyReader),
    ("public_api", ApiKeyHasher, HmacSha256ApiKeyHasher),
    ("public_api", OrganizationReader, SqlaOrganizationReader),
    ("public_api", MembershipChecker, SqlaMembershipChecker),
    ("public_api", UserService, UserService),
    ("public_api", CurrentUserService, CurrentUserService),
    ("public_api", CurrentOrganizationService, CurrentOrganizationService),
    ("public_api", IssueApiKey, IssueApiKey),
    ("public_api", RevokeApiKey, RevokeApiKey),
    ("public_api", ListApiKeys, ListApiKeys),
    ("public_api", GetApiKeyUsageStats, GetApiKeyUsageStats),
    ("public_api", GetOwnProfile, GetOwnProfile),
    ("public_api", ListMyOrganizations, ListMyOrganizations),
    ("public_api", ListOrganizationMembers, ListOrganizationMembers),
    # The CLI: CliProvider (src/app/base/main/cli/provider.py).
    ("cli", PasswordHasher, BcryptPasswordHasher),
    ("cli", IdentityProvider, CliIdentityProvider),
    ("cli", UserFinder, SqlaUserFinder),
    ("cli", AuthzUserFinder, SqlaUserTxStorage),
    ("cli", AccessRevoker, CliAccessRevoker),
    ("cli", UtcTimer, SystemUtcTimer),
    ("cli", UserTxStorage, SqlaUserTxStorage),
    ("cli", Flusher, SqlaFlusher),
    ("cli", TransactionManager, SqlaTransactionManager),
    ("cli", OutboxRepository, SqlaOutboxRepository),
    ("cli", UserReader, SqlaUserReader),
    ("cli", EventDispatcher, HybridEventDispatcher),
    ("cli", UserService, UserService),
    ("cli", CurrentUserService, CurrentUserService),
    ("cli", AuthSessionSqlaTxStorage, AuthSessionSqlaTxStorage),
    ("cli", AuthSqlaTransactionManager, AuthSqlaTransactionManager),
    ("cli", CreateUser, CreateUser),
    ("cli", SetUserPassword, SetUserPassword),
    ("cli", GrantAdmin, GrantAdmin),
    ("cli", RevokeAdmin, RevokeAdmin),
    ("cli", ActivateUser, ActivateUser),
    ("cli", DeactivateUser, DeactivateUser),
    ("cli", ListUsers, ListUsers),
    ("cli", SendWelcomeEmail, SendWelcomeEmail),
    # The worker: WorkerProvider (src/app/base/main/worker/provider.py). The outbox
    # repository is bound by its own class there, not by the OutboxRepository port.
    ("worker", SendWelcomeEmail, SendWelcomeEmail),
    ("worker", SendOrganizationInvitationEmail, SendOrganizationInvitationEmail),
    ("worker", SqlaOutboxRepository, SqlaOutboxRepository),
]

# (entrypoint, what must not be resolvable there); the reasons are in the comments.
ABSENT: list[tuple[Entrypoint, type[Any]]] = [
    # Organization writes stay off the public API until API keys can be scoped
    # (docs/plans/9-organizations.md, Step 15), and none of its interactors raise
    # domain events, so it has no dispatcher and no email sender.
    ("public_api", OrganizationRepository),
    ("public_api", EventDispatcher),
    ("public_api", EmailSender),
    # The CLI manages users only, and subscribes only the welcome email.
    ("cli", OrganizationRepository),
    ("cli", SendOrganizationInvitationEmail),
    # The worker only runs handlers it resolves by dotted path; it never dispatches
    # events and never knows who is calling.
    ("worker", EventDispatcher),
    ("worker", IdentityProvider),
]

# The email sender is chosen from EmailSettings.USE_CONSOLE in every container that has
# one, so both branches are pinned (Step 5 moves these bindings into src/app/shared/).
EMAIL_SENDERS: list[tuple[Entrypoint, bool, type[EmailSender]]] = [
    (entrypoint, use_console, ConsoleEmailSender if use_console else SmtpEmailSender)
    for entrypoint in ("web", "cli", "worker")
    for use_console in (True, False)
]


@pytest.mark.parametrize(
    ("entrypoint", "key", "expected"),
    [pytest.param(*binding, id=f"{binding[0]}-{binding[1].__name__}") for binding in BINDINGS],
)
async def test_each_binding_resolves_to_the_class_bound_today(
    entrypoint: Entrypoint,
    key: type[Any],
    expected: type[Any],
) -> None:
    resolved = await _resolve(entrypoint, key)

    # `type(...) is`, not isinstance: a subclass swapped in is a change too.
    assert type(resolved) is expected


@pytest.mark.parametrize(
    ("entrypoint", "key"),
    [pytest.param(*absent, id=f"{absent[0]}-{absent[1].__name__}") for absent in ABSENT],
)
async def test_a_binding_the_container_must_not_have_is_absent(entrypoint: Entrypoint, key: type[Any]) -> None:
    with pytest.raises(NoFactoryError):
        await _resolve(entrypoint, key)


@pytest.mark.parametrize(
    ("entrypoint", "use_console", "expected"),
    [pytest.param(*sender, id=f"{sender[0]}-use_console_{sender[1]}") for sender in EMAIL_SENDERS],
)
async def test_the_email_sender_follows_use_console(
    entrypoint: Entrypoint,
    use_console: bool,
    expected: type[EmailSender],
) -> None:
    resolved = await _resolve(entrypoint, EmailSender, EmailSettings(USE_CONSOLE=use_console))

    assert type(resolved) is expected


# The pub/sub registry HybridEventDispatcher reads: each event type, and the handlers
# it is delivered to. Written out by hand today in CoreProvider.provide_handler_registry
# and CliProvider.provide_handler_registry; Step 3 builds it from the module registry.
HandlerRegistry = dict[type[DomainEvent], Sequence[EventHandler[Any]]]

# (entrypoint, the subscriptions it has today). A list of pairs rather than a dict, so
# the order of the events and of each event's handlers is pinned too: handlers run in
# list order.
SUBSCRIPTIONS: list[tuple[Entrypoint, list[tuple[type[DomainEvent], list[type[EventHandler[Any]]]]]]] = [
    (
        "web",
        [
            (UserRegisteredEvent, [SendWelcomeEmail]),
            (OrganizationInvitationCreatedEvent, [SendOrganizationInvitationEmail]),
        ],
    ),
    # The CLI can create users, but not invite anyone to an organization.
    ("cli", [(UserRegisteredEvent, [SendWelcomeEmail])]),
]


@pytest.mark.parametrize(
    ("entrypoint", "expected"),
    [pytest.param(*subscriptions, id=subscriptions[0]) for subscriptions in SUBSCRIPTIONS],
)
async def test_the_event_subscriptions_are_todays(
    entrypoint: Entrypoint,
    expected: list[tuple[type[DomainEvent], list[type[EventHandler[Any]]]]],
) -> None:
    registry = await _resolve(entrypoint, HandlerRegistry)

    subscriptions = [(event_type, [type(handler) for handler in handlers]) for event_type, handlers in registry.items()]
    assert subscriptions == expected


# The public API raises no domain events, and the worker resolves each handler by its
# dotted path (src/app/base/main/worker/tasks.py) instead of through a registry.
@pytest.mark.parametrize("entrypoint", ["public_api", "worker"])
async def test_an_entrypoint_without_events_has_no_handler_registry(entrypoint: Entrypoint) -> None:
    with pytest.raises(NoFactoryError):
        await _resolve(entrypoint, HandlerRegistry)
