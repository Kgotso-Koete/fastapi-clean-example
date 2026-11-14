"""
Organizations' dishka providers, one per entrypoint that serves its routes
(docs/plans/16-modular-monolith.md, Decision 13: a unit brings its own
providers per entrypoint). Each is named after the entrypoint it serves, like
Notifications' providers, and binds only what that entrypoint's routes need.

Neither binds what Organizations uses but doesn't own: the database session,
CurrentUserService, UserFinder, UtcTimer, TransactionManager and
EventDispatcher come from each entrypoint's base providers, and
OrganizationSettings from the settings the composition root loads.
"""

from dishka import Provider, Scope, provide

from app.base.core.commands.ports.transaction_manager import TransactionManager
from app.base.core.commands.ports.utc_timer import UtcTimer
from app.base.core.common.ports.event_dispatcher import EventDispatcher
from app.base.core.common.ports.user_finder import UserFinder
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
from app.modules.organizations.core.queries.list_my_invitations import ListMyInvitations
from app.modules.organizations.core.queries.list_my_organizations import ListMyOrganizations
from app.modules.organizations.core.queries.list_organization_members import ListOrganizationMembers
from app.modules.organizations.core.queries.ports.organization_reader import OrganizationReader
from app.modules.organizations.main.config.settings import OrganizationSettings
from app.modules.organizations.outbound.adapters.sqla_membership_checker import SqlaMembershipChecker
from app.modules.organizations.outbound.adapters.sqla_organization_reader import SqlaOrganizationReader
from app.modules.organizations.outbound.adapters.sqla_organization_repository import SqlaOrganizationRepository


class OrganizationsWebProvider(Provider):
    """
    The web app's: every Organizations route, writes and reads, so the
    repository, the reader, the membership check and every use case.
    """

    scope = Scope.REQUEST

    # Ports
    organization_repository = provide(SqlaOrganizationRepository, provides=OrganizationRepository)
    membership_checker = provide(SqlaMembershipChecker, provides=MembershipChecker)
    organization_reader = provide(SqlaOrganizationReader, provides=OrganizationReader)
    # Organization-scoped authorization: every organization-scoped use case
    # calls its require_role() once.
    current_organization_service = provide(CurrentOrganizationService)

    # Commands
    create_organization = provide(CreateOrganization)
    accept_organization_invitation = provide(AcceptOrganizationInvitation)
    decline_organization_invitation = provide(DeclineOrganizationInvitation)
    remove_organization_member = provide(RemoveOrganizationMember)
    change_organization_member_role = provide(ChangeOrganizationMemberRole)
    delete_organization = provide(DeleteOrganization)
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
        # Hand-written: the invitation TTL is a plain int, which dishka can't
        # auto-wire from OrganizationSettings.
        return InviteOrganizationMember(
            current_organization_service=current_organization_service,
            user_finder=user_finder,
            organization_repository=organization_repository,
            utc_timer=utc_timer,
            transaction_manager=transaction_manager,
            invitation_ttl_days=settings.INVITATION_TTL_DAYS,
            event_dispatcher=event_dispatcher,
        )

    # Queries
    list_my_organizations = provide(ListMyOrganizations)
    list_my_invitations = provide(ListMyInvitations)
    list_organization_members = provide(ListOrganizationMembers)


class OrganizationsPublicApiProvider(Provider):
    """
    The public API's: its two read-only routes and what they need. No
    repository and no command: writes stay off the public API until API keys
    can be scoped (docs/plans/9-organizations.md, Step 15).
    """

    scope = Scope.REQUEST

    organization_reader = provide(SqlaOrganizationReader, provides=OrganizationReader)
    membership_checker = provide(SqlaMembershipChecker, provides=MembershipChecker)
    current_organization_service = provide(CurrentOrganizationService)
    list_my_organizations = provide(ListMyOrganizations)
    list_organization_members = provide(ListOrganizationMembers)
