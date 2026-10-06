from datetime import timedelta

import pytest

from app.core.commands.delete_organization import DeleteOrganization, DeleteOrganizationRequest
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager
from tests.unit.core.commands.organizations.factories import NOW, create_current_organization_service
from tests.unit.core.common.services.factories import create_user

# DeleteOrganization (docs/plans/9-organizations.md, Step 11): only an OWNER
# may delete the organization. The use case deletes just the organization row;
# its memberships and invitations go with it through the database's
# ON DELETE CASCADE, which the integration tests prove, not these.


class _FakeOrganizationRepository(OrganizationRepository):
    """Holds organizations by id and records deletions. Membership methods
    aren't used by DeleteOrganization, so they raise NotImplementedError."""

    def __init__(self, organizations: list[Organization]) -> None:
        self.organizations = {o.id_: o for o in organizations}
        self.deleted: list[Organization] = []

    def add(self, organization: Organization) -> None:
        raise NotImplementedError

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        return self.organizations.get(organization_id)

    async def delete(self, organization: Organization) -> None:
        self.deleted.append(organization)

    def add_membership(self, membership: OrganizationMembership) -> None:
        raise NotImplementedError

    async def get_membership_by_id(
        self,
        organization_id: OrganizationId,
        membership_id: OrganizationMembershipId,
    ) -> OrganizationMembership | None:
        raise NotImplementedError

    async def get_membership_for_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> OrganizationMembership | None:
        raise NotImplementedError

    async def delete_membership(self, membership: OrganizationMembership) -> None:
        raise NotImplementedError

    async def count_owners(self, organization_id: OrganizationId) -> int:
        raise NotImplementedError


class _Harness:
    """One existing organization and a caller holding `caller_role` in it
    (None = not a member). `organization_exists=False` simulates the row
    vanishing after the role check passed."""

    def __init__(self, *, caller_role: OrganizationRole | None, organization_exists: bool = True) -> None:
        self.caller = create_user()
        self.organization = Organization(
            id_=create_organization_id(),
            name=OrganizationName("Avengers"),
            description=Description("Earth's mightiest heroes."),
            created_by_user_id=self.caller.id_,
            created_at=UtcDatetime(NOW - timedelta(days=30)),
        )
        self.repository = _FakeOrganizationRepository([self.organization] if organization_exists else [])
        self.transaction_manager = FakeTransactionManager()
        self.sut = DeleteOrganization(
            current_organization_service=create_current_organization_service(self.caller, caller_role),
            organization_repository=self.repository,
            transaction_manager=self.transaction_manager,
        )

    def request(self) -> DeleteOrganizationRequest:
        return DeleteOrganizationRequest(organization_id=self.organization.id_)

    def assert_nothing_deleted(self) -> None:
        assert self.repository.deleted == []
        assert self.transaction_manager.commit_call_count == 0


async def test_an_owner_deletes_the_organization() -> None:
    h = _Harness(caller_role=OrganizationRole.OWNER)

    await h.sut.execute(h.request())

    # Exactly this organization, then one commit -- the cascade does the rest.
    assert h.repository.deleted == [h.organization]
    assert h.transaction_manager.commit_call_count == 1


@pytest.mark.parametrize(
    "caller_role",
    [
        pytest.param(OrganizationRole.ADMIN, id="admin"),
        pytest.param(OrganizationRole.MEMBER, id="member"),
    ],
)
async def test_an_admin_or_member_cannot_delete_the_organization(caller_role: OrganizationRole) -> None:
    # Deleting is irreversible and takes every member with it, so it's the
    # owner's call alone -- an ADMIN can manage people, not end the organization.
    h = _Harness(caller_role=caller_role)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(h.request())

    h.assert_nothing_deleted()


async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    # 404 rather than 403, as everywhere in this context: an outsider can't
    # even confirm the organization exists.
    h = _Harness(caller_role=None)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request())

    h.assert_nothing_deleted()


async def test_an_organization_gone_after_the_role_check_is_not_found() -> None:
    # require_role() proved the organization existed a moment ago; if it's
    # gone by the time it's loaded (deleted concurrently), that's still a
    # plain 404, never a crash on None.
    h = _Harness(caller_role=OrganizationRole.OWNER, organization_exists=False)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request())

    h.assert_nothing_deleted()
