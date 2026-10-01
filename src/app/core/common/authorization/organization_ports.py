from abc import abstractmethod
from typing import Protocol

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.entities.types_ import UserId

# Kept in its own module, next to (not inside) ports.py, so the Organizations
# feature is purely additive -- same reasoning as organization_permissions.py.
# Shared by every organization-scoped feature, exactly like AuthzUserFinder
# is shared by every platform-level Permission, rather than redefined per
# feature.


class MembershipChecker(Protocol):
    @abstractmethod
    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        """
        The role this user holds in THIS organization, or None if they hold
        no ACCEPTED membership in it -- a non-member, a still-pending
        invitee, and a member of a different organization all resolve to
        None, which CanAccessOrganization always denies.

        Async because it queries storage, which is why it's called BEFORE
        authorize(): the result is placed on an OrganizationAccessContext,
        and CanAccessOrganization.is_satisfied_by() itself never does I/O.
        """
        ...
