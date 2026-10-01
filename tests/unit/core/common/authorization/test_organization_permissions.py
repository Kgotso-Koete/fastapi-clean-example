import pytest

from app.core.common.authorization.organization_permissions import (
    CanAccessOrganization,
    OrganizationAccessContext,
)
from app.core.common.entities.organization_membership import OrganizationRole

# Unlike the platform-level ROLE_HIERARCHY (where an ADMIN cannot manage
# another ADMIN), every organization role satisfies its OWN level too: the
# question CanAccessOrganization answers is "does this member hold at least
# this role?", not "may this member manage someone of that role?".


@pytest.mark.parametrize(
    "minimum_role",
    [
        pytest.param(OrganizationRole.OWNER, id="owner_minimum"),
        pytest.param(OrganizationRole.ADMIN, id="admin_minimum"),
        pytest.param(OrganizationRole.MEMBER, id="member_minimum"),
    ],
)
def test_a_non_member_is_denied_whatever_the_minimum_role(minimum_role: OrganizationRole) -> None:
    # member_role=None is what MembershipChecker.get_role() resolves to for a
    # user with no ACCEPTED membership -- including a still-pending invitee.
    context = OrganizationAccessContext(member_role=None, minimum_role=minimum_role)
    sut = CanAccessOrganization()

    assert not sut.is_satisfied_by(context)


@pytest.mark.parametrize(
    ("member_role", "minimum_role"),
    [
        pytest.param(OrganizationRole.OWNER, OrganizationRole.OWNER, id="owner_meets_owner"),
        pytest.param(OrganizationRole.OWNER, OrganizationRole.ADMIN, id="owner_meets_admin"),
        pytest.param(OrganizationRole.OWNER, OrganizationRole.MEMBER, id="owner_meets_member"),
        pytest.param(OrganizationRole.ADMIN, OrganizationRole.ADMIN, id="admin_meets_admin"),
        pytest.param(OrganizationRole.ADMIN, OrganizationRole.MEMBER, id="admin_meets_member"),
        pytest.param(OrganizationRole.MEMBER, OrganizationRole.MEMBER, id="member_meets_member"),
    ],
)
def test_a_role_satisfies_its_own_and_every_lower_minimum(
    member_role: OrganizationRole,
    minimum_role: OrganizationRole,
) -> None:
    context = OrganizationAccessContext(member_role=member_role, minimum_role=minimum_role)
    sut = CanAccessOrganization()

    assert sut.is_satisfied_by(context)


@pytest.mark.parametrize(
    ("member_role", "minimum_role"),
    [
        pytest.param(OrganizationRole.ADMIN, OrganizationRole.OWNER, id="admin_fails_owner"),
        pytest.param(OrganizationRole.MEMBER, OrganizationRole.ADMIN, id="member_fails_admin"),
        pytest.param(OrganizationRole.MEMBER, OrganizationRole.OWNER, id="member_fails_owner"),
    ],
)
def test_a_role_never_satisfies_a_higher_minimum(
    member_role: OrganizationRole,
    minimum_role: OrganizationRole,
) -> None:
    context = OrganizationAccessContext(member_role=member_role, minimum_role=minimum_role)
    sut = CanAccessOrganization()

    assert not sut.is_satisfied_by(context)
