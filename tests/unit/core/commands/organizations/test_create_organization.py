from datetime import UTC, datetime

import pytest

from app.core.commands.create_organization import CreateOrganization, CreateOrganizationRequest
from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.organization_name import OrganizationName
from app.core.common.value_objects.utc_datetime import UtcDatetime
from tests.unit.core.commands.api_keys.factories import FakeTransactionManager, FakeUtcTimer
from tests.unit.core.common.authorization.factories import (
    FakeAccessRevoker,
    FakeAuthzUserFinder,
    FakeIdentityProvider,
    create_current_user_service,
)
from tests.unit.core.common.services.factories import create_user

_NOW = UtcDatetime(datetime(2026, 6, 1, tzinfo=UTC))
# Every organization must explain itself, so every request carries one.
_DESCRIPTION = "Earth's mightiest heroes."


class FakeOrganizationRepository(OrganizationRepository):
    """Records every Organization/OrganizationMembership passed to add()/
    add_membership(). The lookup methods aren't needed by CreateOrganization
    -- raising NotImplementedError makes an unexpected call fail loudly
    instead of silently returning None, same as FakeApiKeyRepository.

    `log` is optional and shared with _RecordingTransactionManager below,
    so a test can assert on the ORDER of adds vs. commit."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.added: list[Organization] = []
        self.added_memberships: list[OrganizationMembership] = []
        self._log = log if log is not None else []

    def add(self, organization: Organization) -> None:
        self._log.append("add")
        self.added.append(organization)

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        raise NotImplementedError

    async def delete(self, organization: Organization) -> None:
        raise NotImplementedError

    def add_membership(self, membership: OrganizationMembership) -> None:
        self._log.append("add_membership")
        self.added_memberships.append(membership)

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


class _RecordingTransactionManager(TransactionManager):
    """Writes "commit" into the same log the repository writes into."""

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log.append("commit")


def _make_sut(
    *,
    current_user_service: CurrentUserService,
    organization_repository: OrganizationRepository | None = None,
    transaction_manager: TransactionManager | None = None,
) -> CreateOrganization:
    return CreateOrganization(
        current_user_service=current_user_service,
        organization_repository=organization_repository or FakeOrganizationRepository(),
        utc_timer=FakeUtcTimer(_NOW),
        transaction_manager=transaction_manager or FakeTransactionManager(),
    )


@pytest.mark.asyncio
async def test_creates_the_organization_named_and_owned_by_the_current_user() -> None:
    user = create_user()
    repository = FakeOrganizationRepository()
    sut = _make_sut(current_user_service=create_current_user_service(user), organization_repository=repository)

    await sut.execute(CreateOrganizationRequest(name="Avengers", description=_DESCRIPTION))

    assert len(repository.added) == 1
    organization = repository.added[0]
    assert organization.name == OrganizationName("Avengers")
    assert organization.description == Description(_DESCRIPTION)
    assert organization.created_by_user_id == user.id_
    assert organization.created_at == _NOW


@pytest.mark.asyncio
async def test_the_creator_becomes_an_accepted_owner_in_the_same_organization() -> None:
    # The creator needs no self-invite: their OWNER membership is accepted
    # from the moment the organization exists.
    user = create_user()
    repository = FakeOrganizationRepository()
    sut = _make_sut(current_user_service=create_current_user_service(user), organization_repository=repository)

    await sut.execute(CreateOrganizationRequest(name="Avengers", description=_DESCRIPTION))

    assert len(repository.added_memberships) == 1
    membership = repository.added_memberships[0]
    assert membership.organization_id == repository.added[0].id_
    assert membership.user_id == user.id_
    assert membership.invited_by_user_id == user.id_
    assert membership.role == OrganizationRole.OWNER
    assert membership.is_accepted
    assert membership.accepted_at == _NOW


@pytest.mark.asyncio
async def test_organization_and_owner_membership_are_committed_together_once() -> None:
    # Both rows are staged BEFORE a single commit -- one transaction, so an
    # organization can never exist without its owner (or vice versa).
    user = create_user()
    log: list[str] = []
    sut = _make_sut(
        current_user_service=create_current_user_service(user),
        organization_repository=FakeOrganizationRepository(log),
        transaction_manager=_RecordingTransactionManager(log),
    )

    await sut.execute(CreateOrganizationRequest(name="Avengers", description=_DESCRIPTION))

    assert log == ["add", "add_membership", "commit"]


@pytest.mark.asyncio
async def test_returns_the_new_organizations_id_name_description_and_created_at() -> None:
    user = create_user()
    repository = FakeOrganizationRepository()
    sut = _make_sut(current_user_service=create_current_user_service(user), organization_repository=repository)

    response = await sut.execute(CreateOrganizationRequest(name="  Avengers  ", description=f"  {_DESCRIPTION}\n"))

    assert response["id"] == repository.added[0].id_
    # The response carries the normalized (trimmed) name and description,
    # as stored.
    assert response["name"] == "Avengers"
    assert response["description"] == _DESCRIPTION
    assert response["created_at"] == _NOW.value


@pytest.mark.asyncio
async def test_an_unresolvable_current_user_creates_nothing() -> None:
    # A real CurrentUserService whose user lookup finds nothing raises
    # AuthorizationError itself -- nothing may be staged or committed.
    user = create_user()
    current_user_service = CurrentUserService(
        identity_provider=FakeIdentityProvider(user.id_),
        authz_user_finder=FakeAuthzUserFinder(None),
        access_revoker=FakeAccessRevoker(),
    )
    repository = FakeOrganizationRepository()
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(
        current_user_service=current_user_service,
        organization_repository=repository,
        transaction_manager=transaction_manager,
    )

    with pytest.raises(AuthorizationError):
        await sut.execute(CreateOrganizationRequest(name="Avengers", description=_DESCRIPTION))

    assert repository.added == []
    assert repository.added_memberships == []
    assert transaction_manager.commit_call_count == 0


@pytest.mark.parametrize(
    ("name", "description"),
    [
        # OrganizationName's own rules (tested in test_organization_name.py).
        pytest.param("   ", _DESCRIPTION, id="blank_name"),
        # Description's own rules (tested in test_description.py): mandatory,
        # so a blank one is as invalid as a blank name.
        pytest.param("Avengers", "   ", id="blank_description"),
    ],
)
@pytest.mark.asyncio
async def test_an_invalid_name_or_description_creates_nothing(name: str, description: str) -> None:
    # Both are validated before anything is staged or committed.
    user = create_user()
    repository = FakeOrganizationRepository()
    transaction_manager = FakeTransactionManager()
    sut = _make_sut(
        current_user_service=create_current_user_service(user),
        organization_repository=repository,
        transaction_manager=transaction_manager,
    )

    with pytest.raises(BusinessTypeError):
        await sut.execute(CreateOrganizationRequest(name=name, description=description))

    assert repository.added == []
    assert repository.added_memberships == []
    assert transaction_manager.commit_call_count == 0
