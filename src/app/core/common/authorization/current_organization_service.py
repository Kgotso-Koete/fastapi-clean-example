from app.core.common.authorization.authorize import authorize
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.authorization.organization_permissions import (
    CanAccessOrganization,
    OrganizationAccessContext,
)
from app.core.common.authorization.organization_ports import MembershipChecker
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.entities.user import User


class CurrentOrganizationService:
    """
    The organization-scoped counterpart of CurrentUserService: every
    organization-scoped command/query calls require_role() once, the same
    way every existing command calls CurrentUserService.get_current_user().

    Takes an already-parsed organization_id rather than reading the request
    itself -- each HTTP route declares `organization_id: Annotated[UUID,
    Path()]`, so a malformed id 422s before this service is ever reached.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        membership_checker: MembershipChecker,
    ) -> None:
        self._current_user_service = current_user_service
        self._membership_checker = membership_checker

    async def require_role(
        self,
        organization_id: OrganizationId,
        minimum_role: OrganizationRole,
    ) -> tuple[OrganizationId, User]:
        # 1. Who is calling -- raises AuthorizationError itself for an
        #    unknown/inactive user, so the membership lookup never runs.
        current_user = await self._current_user_service.get_current_user()
        # 2. Their role in THIS organization. Async I/O, so it happens here,
        #    BEFORE authorize() -- CanAccessOrganization never does I/O.
        member_role = await self._membership_checker.get_role(current_user.id_, organization_id)
        # 3. Not a member at all -> 404, before authorize() even runs, so an
        #    outsider can't confirm the organization exists.
        if member_role is None:
            raise OrganizationNotFoundError
        # 4. A real member: the synchronous decision -- a role below
        #    minimum_role raises AuthorizationError (403).
        authorize(
            CanAccessOrganization(),
            context=OrganizationAccessContext(member_role=member_role, minimum_role=minimum_role),
        )
        return organization_id, current_user
