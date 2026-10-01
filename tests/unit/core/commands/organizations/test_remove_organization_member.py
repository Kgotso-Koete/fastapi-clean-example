from uuid import uuid4

import pytest

from app.core.commands.organization_exceptions import (
    CannotManageOwnerError,
    LastOwnerError,
    MembershipNotFoundError,
)
from app.core.commands.remove_organization_member import (
    RemoveOrganizationMember,
    RemoveOrganizationMemberRequest,
)
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import OrganizationId
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

# RemoveOrganizationMember (docs/plans/9-organizations.md, Step 7): deletes a
# membership row, pending or accepted. Rules, from apptension/saas-boilerplate's
# DeleteTenantMembershipMutation:
#   - removing yourself is LEAVING, and any member may leave;
#   - removing someone else needs ADMIN (a pending row = revoking an invite);
#   - only an OWNER may remove another OWNER;
#   - the last accepted OWNER can never be removed, including by leaving.


class _Harness:
    """One organization, the caller (with their own role), and whatever other
    memberships a test adds. The caller's own membership row is created too,
    so "leaving" has a real row to delete."""

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
        self.sut = RemoveOrganizationMember(
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

    def request(self, membership_id: OrganizationMembershipId) -> RemoveOrganizationMemberRequest:
        return RemoveOrganizationMemberRequest(organization_id=self.organization_id, membership_id=membership_id)

    def own_membership_id(self) -> OrganizationMembershipId:
        assert self.caller_membership is not None
        return self.caller_membership.id_

    def assert_removed(self, membership: OrganizationMembership) -> None:
        assert self.repository.deleted == [membership]
        assert self.transaction_manager.commit_call_count == 1

    def assert_nothing_removed(self) -> None:
        assert self.repository.deleted == []
        assert self.transaction_manager.commit_call_count == 0


# --- 1-3. Leaving -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_role", [OrganizationRole.MEMBER, OrganizationRole.ADMIN])
async def test_any_member_can_leave(caller_role: OrganizationRole) -> None:
    # Without this, a plain MEMBER could never leave an organization.
    h = _Harness(caller_role=caller_role)
    h.add_member(OrganizationRole.OWNER)

    await h.sut.execute(h.request(h.own_membership_id()))

    assert h.caller_membership is not None
    h.assert_removed(h.caller_membership)


@pytest.mark.asyncio
async def test_an_owner_can_leave_when_another_owner_remains() -> None:
    h = _Harness(caller_role=OrganizationRole.OWNER)
    h.add_member(OrganizationRole.OWNER)

    await h.sut.execute(h.request(h.own_membership_id()))

    assert h.caller_membership is not None
    h.assert_removed(h.caller_membership)


@pytest.mark.asyncio
async def test_the_last_owner_cannot_leave() -> None:
    # A pending OWNER invitation doesn't count as a remaining owner. The way
    # out is to promote someone else to OWNER first.
    h = _Harness(caller_role=OrganizationRole.OWNER)
    h.add_member(OrganizationRole.OWNER, accepted=False)
    h.add_member(OrganizationRole.ADMIN)

    with pytest.raises(LastOwnerError):
        await h.sut.execute(h.request(h.own_membership_id()))

    h.assert_nothing_removed()


# --- 4-5. Removing someone else, as an ADMIN or OWNER -------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_role", [OrganizationRole.ADMIN, OrganizationRole.OWNER])
@pytest.mark.parametrize("target_role", [OrganizationRole.MEMBER, OrganizationRole.ADMIN])
async def test_an_admin_or_owner_removes_a_member_or_admin(
    caller_role: OrganizationRole,
    target_role: OrganizationRole,
) -> None:
    h = _Harness(caller_role=caller_role)
    h.add_member(OrganizationRole.OWNER)
    target = h.add_member(target_role)

    await h.sut.execute(h.request(target.id_))

    h.assert_removed(target)


@pytest.mark.asyncio
async def test_an_admin_revokes_a_pending_invitation() -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)
    invitation = h.add_member(OrganizationRole.MEMBER, accepted=False)

    await h.sut.execute(h.request(invitation.id_))

    h.assert_removed(invitation)


# --- 6-8. Who may NOT remove whom ---------------------------------------------


@pytest.mark.asyncio
async def test_a_member_cannot_remove_someone_else() -> None:
    # A real member, so 403 (they know the organization exists), not 404.
    h = _Harness(caller_role=OrganizationRole.MEMBER)
    target = h.add_member(OrganizationRole.MEMBER)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(h.request(target.id_))

    h.assert_nothing_removed()


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False], ids=["owner", "pending_owner_invitation"])
async def test_an_admin_cannot_remove_an_owner(accepted: bool) -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)
    h.add_member(OrganizationRole.OWNER)
    target = h.add_member(OrganizationRole.OWNER, accepted=accepted)

    with pytest.raises(CannotManageOwnerError):
        await h.sut.execute(h.request(target.id_))

    h.assert_nothing_removed()


@pytest.mark.asyncio
async def test_an_owner_can_remove_another_owner() -> None:
    h = _Harness(caller_role=OrganizationRole.OWNER)
    target = h.add_member(OrganizationRole.OWNER)

    await h.sut.execute(h.request(target.id_))

    h.assert_removed(target)


# --- 9-10. Not a member, or no such membership ---------------------------------


@pytest.mark.asyncio
async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    h = _Harness(caller_role=None)
    target = h.add_member(OrganizationRole.MEMBER)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request(target.id_))

    # Refused before the target is even looked up.
    assert h.repository.lookups == []
    h.assert_nothing_removed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "look_in_another_organization",
    [
        pytest.param(False, id="unknown_membership_id"),
        pytest.param(True, id="membership_of_another_organization"),
    ],
)
async def test_an_unknown_or_out_of_scope_membership_is_not_found(look_in_another_organization: bool) -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)
    elsewhere = create_membership(
        organization_id=OrganizationId(uuid4()),
        user=create_user(),
        role=OrganizationRole.MEMBER,
    )
    h.repository.memberships.append(elsewhere)
    membership_id = elsewhere.id_ if look_in_another_organization else OrganizationMembershipId(uuid4())

    with pytest.raises(MembershipNotFoundError):
        await h.sut.execute(h.request(membership_id))

    h.assert_nothing_removed()
