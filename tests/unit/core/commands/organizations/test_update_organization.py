from datetime import timedelta

import pytest

from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.update_organization import UpdateOrganization, UpdateOrganizationRequest
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.exceptions import BusinessTypeError
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager
from tests.unit.core.commands.organizations.factories import NOW, create_current_organization_service
from tests.unit.core.common.services.factories import create_user

# UpdateOrganization (docs/plans/9-organizations.md, Step 13): an ADMIN or
# OWNER changes the organization's name and/or description. A partial update:
# a field left out stays as it is, and neither can be cleared, because both
# are mandatory value objects.

_NAME = "Avengers"
_DESCRIPTION = "Earth's mightiest heroes."


class _FakeOrganizationRepository(OrganizationRepository):
    """Holds organizations by id. Nothing else is used by UpdateOrganization,
    so every other method raises NotImplementedError."""

    def __init__(self, organizations: list[Organization]) -> None:
        self.organizations = {o.id_: o for o in organizations}

    def add(self, organization: Organization) -> None:
        raise NotImplementedError

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        return self.organizations.get(organization_id)

    async def delete(self, organization: Organization) -> None:
        raise NotImplementedError

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
    """One existing "Avengers" organization and a caller holding
    `caller_role` in it (None = not a member). `organization_exists=False`
    simulates the row vanishing after the role check passed."""

    def __init__(self, *, caller_role: OrganizationRole | None, organization_exists: bool = True) -> None:
        self.caller = create_user()
        self.organization = Organization(
            id_=create_organization_id(),
            name=OrganizationName(_NAME),
            description=Description(_DESCRIPTION),
            created_by_user_id=self.caller.id_,
            created_at=UtcDatetime(NOW - timedelta(days=30)),
        )
        self.repository = _FakeOrganizationRepository([self.organization] if organization_exists else [])
        self.transaction_manager = FakeTransactionManager()
        self.sut = UpdateOrganization(
            current_organization_service=create_current_organization_service(self.caller, caller_role),
            organization_repository=self.repository,
            transaction_manager=self.transaction_manager,
        )

    def request(self, *, name: str | None = None, description: str | None = None) -> UpdateOrganizationRequest:
        return UpdateOrganizationRequest(organization_id=self.organization.id_, name=name, description=description)

    def assert_nothing_changed(self) -> None:
        assert self.organization.name == OrganizationName(_NAME)
        assert self.organization.description == Description(_DESCRIPTION)
        assert self.transaction_manager.commit_call_count == 0


@pytest.mark.parametrize(
    "caller_role",
    [
        pytest.param(OrganizationRole.ADMIN, id="admin"),
        pytest.param(OrganizationRole.OWNER, id="owner"),
    ],
)
async def test_an_admin_or_owner_updates_the_name_and_description(caller_role: OrganizationRole) -> None:
    h = _Harness(caller_role=caller_role)

    response = await h.sut.execute(h.request(name="New Avengers", description="Assembled again."))

    assert h.organization.name == OrganizationName("New Avengers")
    assert h.organization.description == Description("Assembled again.")
    assert h.transaction_manager.commit_call_count == 1
    assert response == {"id": h.organization.id_, "name": "New Avengers", "description": "Assembled again."}


@pytest.mark.parametrize(
    ("name", "description", "expected_name", "expected_description"),
    [
        pytest.param("New Avengers", None, "New Avengers", _DESCRIPTION, id="only_name"),
        pytest.param(None, "Assembled again.", _NAME, "Assembled again.", id="only_description"),
        # Nothing to change is still a valid PATCH: the organization comes
        # back as it is.
        pytest.param(None, None, _NAME, _DESCRIPTION, id="neither"),
    ],
)
async def test_a_field_left_out_is_unchanged(
    name: str | None,
    description: str | None,
    expected_name: str,
    expected_description: str,
) -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)

    response = await h.sut.execute(h.request(name=name, description=description))

    assert h.organization.name == OrganizationName(expected_name)
    assert h.organization.description == Description(expected_description)
    assert response["name"] == expected_name
    assert response["description"] == expected_description


async def test_the_response_carries_the_trimmed_values_as_stored() -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)

    response = await h.sut.execute(h.request(name="  New Avengers  ", description="\n Assembled again. \n"))

    assert response["name"] == "New Avengers"
    assert response["description"] == "Assembled again."


@pytest.mark.parametrize(
    ("name", "description"),
    [
        pytest.param("   ", None, id="blank_name"),
        # Mandatory, so "clearing" it is just a blank, invalid description.
        pytest.param(None, "", id="blank_description"),
        # A valid name must not be applied when the description is invalid:
        # both are checked before either changes.
        pytest.param("New Avengers", "   ", id="valid_name_with_blank_description"),
    ],
)
async def test_an_invalid_value_changes_nothing(name: str | None, description: str | None) -> None:
    h = _Harness(caller_role=OrganizationRole.ADMIN)

    with pytest.raises(BusinessTypeError):
        await h.sut.execute(h.request(name=name, description=description))

    h.assert_nothing_changed()


async def test_a_member_cannot_update_the_organization() -> None:
    # Renaming changes what every member sees, so it's an ADMIN's job.
    h = _Harness(caller_role=OrganizationRole.MEMBER)

    with pytest.raises(AuthorizationError):
        await h.sut.execute(h.request(name="New Avengers"))

    h.assert_nothing_changed()


async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    # 404 rather than 403, as everywhere in this context.
    h = _Harness(caller_role=None)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request(name="New Avengers"))

    h.assert_nothing_changed()


async def test_an_organization_gone_after_the_role_check_is_not_found() -> None:
    # Deleted concurrently between require_role() and the load: a plain 404.
    h = _Harness(caller_role=OrganizationRole.OWNER, organization_exists=False)

    with pytest.raises(OrganizationNotFoundError):
        await h.sut.execute(h.request(name="New Avengers"))

    assert h.transaction_manager.commit_call_count == 0
