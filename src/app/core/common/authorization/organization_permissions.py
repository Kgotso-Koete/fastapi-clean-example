from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core.common.authorization.base import Permission, PermissionContext
from app.core.common.entities.organization_membership import OrganizationRole

# Kept in its own module, next to (not inside) permissions.py/role_hierarchy.py,
# so the Organizations feature is purely additive: deleting this file removes
# it without touching the platform-level UserRole permissions at all.
#
# Maps each role to every MINIMUM role it satisfies -- each role includes its
# own level, unlike ROLE_HIERARCHY (role_hierarchy.py), because this answers
# "does this member hold at least this role?", not "may they manage that role?".
ORGANIZATION_ROLE_HIERARCHY: Final[Mapping[OrganizationRole, set[OrganizationRole]]] = {
    OrganizationRole.OWNER: {OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER},
    OrganizationRole.ADMIN: {OrganizationRole.ADMIN, OrganizationRole.MEMBER},
    OrganizationRole.MEMBER: {OrganizationRole.MEMBER},
}


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationAccessContext(PermissionContext):
    # member_role is resolved by calling MembershipChecker.get_role() BEFORE
    # authorize() is invoked -- is_satisfied_by() below is synchronous, like
    # every other Permission in this codebase, and never performs I/O itself.
    # None means "no ACCEPTED membership" (a non-member or a pending invitee).
    member_role: OrganizationRole | None
    minimum_role: OrganizationRole


class CanAccessOrganization(Permission[OrganizationAccessContext]):
    def __init__(
        self,
        role_hierarchy: Mapping[OrganizationRole, set[OrganizationRole]] = ORGANIZATION_ROLE_HIERARCHY,
    ) -> None:
        # Injectable with a default, mirroring CanManageRole/CanManageSubordinate,
        # so a fork can extend the hierarchy without editing this class.
        self._role_hierarchy = role_hierarchy

    def is_satisfied_by(self, context: OrganizationAccessContext) -> bool:
        if context.member_role is None:
            return False
        return context.minimum_role in self._role_hierarchy.get(context.member_role, set())
