from uuid import uuid4

import pytest

from app.core.commands.change_organization_member_role import (
    ChangeOrganizationMemberRole,
    ChangeOrganizationMemberRoleRequest,
)
from app.core.commands.organization_exceptions import (
    CannotGrantOwnerRoleError,
    CannotManageOwnerError,
    LastOwnerError,
    MembershipNotFoundError,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.factories.organization_id_factory import create_organization_id
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager
from tests.unit.core.commands.organizations.factories import (
    FakeMembershipsRepository,
    create_current_organization_service,
    create_membership,
)
from tests.unit.core.common.services.factories import create_user

# ChangeOrganizationMemberRole (docs/plans/9-organizations.md, Step 7). Rules,
# from apptension/saas-boilerplate's UpdateTenantMembershipSerializer:
#   - needs ADMIN;
#   - only an OWNER may grant OWNER, or change another OWNER's role;
#   - demoting the last accepted OWNER is refused (LastOwnerError).
# Promoting someone else to OWNER is how ownership is transferred.


class _Harness:
    """One organization and the caller (with their own membership row); tests
    add the membership whose role is being changed."""

    def __init__(self, *, caller_role: OrganizationRole | None) -> None:
        self.organization_id = create_organization_id()
        self.caller = create_user()
        self.caller_membership: OrganizationMembership | None = None
        memberships: list[OrganizationMembership] = []
        if caller_role is not None:
            self.caller_membership = create_membership(
                organization_id=self.organization_id,
                user=self.caller,
                role=caller_role,
            )
            memberships.append(self.caller_membership)
        self.repository = FakeMembershipsRepository(memberships)
        self.transaction_manager = FakeTransactionManager()
        self.sut = ChangeOrganizationMemberRole(
            current_organization_service=create_current_organization_service(self.caller, caller_role),
            organization_repository=self.repository,
            transaction_manager=self.transaction_manager,
        )

    def add_member(self, role: OrganizationRole, *, accepted: bool = True) -> OrganizationMembership:
        membership = create_membership(
            organization_id=self.organization_id,
            user=create_user(),
            role=role,
            accepted=accepted,
        )
        self.repository.memberships.append(membership)
        return membership

    def request(
        self,
        membership_id: OrganizationMembershipId,
        role: OrganizationRole,
    ) -> ChangeOrganizationMemberRoleRequest:
        return ChangeOrganizationMemberRoleRequest(
            organization_id=self.organization_id,
            membership_id=membership_id,
            role=role,
        )

    def assert_unchanged(self, membership: OrganizationMembership, role: OrganizationRole) -> None:
        assert membership.role == role
        assert self.transaction_manager.commit_call_count == 0


# --- 1-2. The happy paths ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_role", [OrganizationRole.ADMIN, OrganizationRole.OWNER])
async def test_an_admin_or_owner_changes_a_members_role(caller_role: OrganizationRole) -> None:
    h = _Harness(caller_role=caller_role)
    target = h.add_member(OrganizationRole.MEMBER)

    await h.sut.execute(h.request(target.id_, OrganizationRole.ADMIN))

    assert target.role == OrganizationRole.ADMIN
    assert h.transaction_manager.commit_call_count == 1


@pytest.mark.asyncio
async def test_an_owner_transfers_ownership_by_promoting_a_member() -> None:
    h = _Harness(caller_role=OrganizationRole.OWNER)
    target = h.add_member(OrganizationRole.MEMBER)

    await h.sut.execute(h.request(target.id_, OrganizationRole.OWNER))

    assert target.role == OrganizationRole.OWNER
    assert h.transaction_manager.commit_call_count == 1


# --- 3-4. Who may change roles at all ----------------------------------------------


@pytest.mark.asyncio
async def test_a_member_cannot_change_roles() -> None:
    h = _Harness(caller_role=OrganizationRole.MEMBER)
    target = h.add_member(OrganizationRole.MEMBER)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(h.request(target.id_, OrganizationRole.ADMIN))

    h.assert_unchanged(target, OrganizationRole.MEMBER)


@pytest.mark.asyncio
async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    h = _Harness(caller_role=None)
    target = h.add_member(OrganizationRole.MEMBER)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request(target.id_, OrganizationRole.ADMIN))

    assert h.repository.lookups == []
    h.assert_unchanged(target, OrganizationRole.MEMBER)


# --- 5-6. The OWNER role is the OWNER's to hand out or take away ------------------


@pytest.mark.asyncio
async def test_an_admin_cannot_grant_owner() -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)
    target = h.add_member(OrganizationRole.MEMBER)

    with pytest.raises(CannotGrantOwnerRoleError):
        await h.sut.execute(h.request(target.id_, OrganizationRole.OWNER))

    h.assert_unchanged(target, OrganizationRole.MEMBER)


@pytest.mark.asyncio
async def test_an_admin_cannot_change_an_owners_role() -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)
    h.add_member(OrganizationRole.OWNER)
    target = h.add_member(OrganizationRole.OWNER)

    with pytest.raises(CannotManageOwnerError):
        await h.sut.execute(h.request(target.id_, OrganizationRole.MEMBER))

    h.assert_unchanged(target, OrganizationRole.OWNER)


# --- 7-8. The last owner ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_owner_demotes_another_owner_when_one_remains() -> None:
    h = _Harness(caller_role=OrganizationRole.OWNER)
    target = h.add_member(OrganizationRole.OWNER)

    await h.sut.execute(h.request(target.id_, OrganizationRole.ADMIN))

    assert target.role == OrganizationRole.ADMIN
    assert h.transaction_manager.commit_call_count == 1


@pytest.mark.asyncio
async def test_the_last_owner_cannot_demote_themselves() -> None:
    # A pending OWNER invitation isn't a remaining owner.
    h = _Harness(caller_role=OrganizationRole.OWNER)
    h.add_member(OrganizationRole.OWNER, accepted=False)
    assert h.caller_membership is not None

    with pytest.raises(LastOwnerError):
        await h.sut.execute(h.request(h.caller_membership.id_, OrganizationRole.ADMIN))

    h.assert_unchanged(h.caller_membership, OrganizationRole.OWNER)


# --- 9. No such membership ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_membership_is_not_found() -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)

    with pytest.raises(MembershipNotFoundError):
        await h.sut.execute(h.request(OrganizationMembershipId(uuid4()), OrganizationRole.ADMIN))

    assert h.transaction_manager.commit_call_count == 0
