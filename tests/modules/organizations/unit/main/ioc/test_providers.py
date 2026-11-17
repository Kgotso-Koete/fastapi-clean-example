from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.exceptions import NoFactoryError
from sqlalchemy.ext.asyncio import AsyncSession

from app.base.core.commands.ports.transaction_manager import TransactionManager
from app.base.core.commands.ports.utc_timer import UtcTimer
from app.base.core.common.authorization.current_user_service import CurrentUserService
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
from app.modules.organizations.main.ioc.providers import (
    OrganizationsPublicApiProvider,
    OrganizationsWebProvider,
)
from app.modules.organizations.outbound.adapters.sqla_membership_checker import SqlaMembershipChecker
from app.modules.organizations.outbound.adapters.sqla_organization_reader import SqlaOrganizationReader
from app.modules.organizations.outbound.adapters.sqla_organization_repository import SqlaOrganizationRepository

# Organizations' own providers, one per entrypoint that serves its routes
# (docs/plans/16-modular-monolith.md, Decision 13: a unit brings its providers
# per entrypoint). Each test builds a small real dishka container from one of
# them, so what is checked is what dishka actually builds.

# Each port or use case the web app binds for Organizations today, mapped to the
# class it resolves to (tests/base/characterisation/main/test_container_bindings.py,
# BINDINGS). A use case resolves to itself.
WEB_BINDINGS: Mapping[Any, type[Any]] = {
    OrganizationRepository: SqlaOrganizationRepository,
    MembershipChecker: SqlaMembershipChecker,
    OrganizationReader: SqlaOrganizationReader,
    CurrentOrganizationService: CurrentOrganizationService,
    CreateOrganization: CreateOrganization,
    InviteOrganizationMember: InviteOrganizationMember,
    AcceptOrganizationInvitation: AcceptOrganizationInvitation,
    DeclineOrganizationInvitation: DeclineOrganizationInvitation,
    RemoveOrganizationMember: RemoveOrganizationMember,
    ChangeOrganizationMemberRole: ChangeOrganizationMemberRole,
    UpdateOrganization: UpdateOrganization,
    DeleteOrganization: DeleteOrganization,
    ListMyOrganizations: ListMyOrganizations,
    ListMyInvitations: ListMyInvitations,
    ListOrganizationMembers: ListOrganizationMembers,
}

# The public API's: the two read-only routes and what they need, no writes.
PUBLIC_API_BINDINGS: Mapping[Any, type[Any]] = {
    OrganizationReader: SqlaOrganizationReader,
    MembershipChecker: SqlaMembershipChecker,
    CurrentOrganizationService: CurrentOrganizationService,
    ListMyOrganizations: ListMyOrganizations,
    ListOrganizationMembers: ListOrganizationMembers,
}


# Stands in for what each entrypoint's base providers bind, and Organizations
# uses but never binds itself: the database session, the current user, the
# user lookup, the clock, the transaction, event dispatch, and the settings the
# composition root loads. Mocks, because only the wiring is under test.
class FakeBaseProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def provide_session(self) -> AsyncSession:
        return AsyncMock()

    @provide
    def provide_current_user_service(self) -> CurrentUserService:
        return AsyncMock()

    @provide
    def provide_user_finder(self) -> UserFinder:
        return AsyncMock()

    @provide
    def provide_utc_timer(self) -> UtcTimer:
        return AsyncMock()

    @provide
    def provide_transaction_manager(self) -> TransactionManager:
        return AsyncMock()

    @provide
    def provide_event_dispatcher(self) -> EventDispatcher:
        return AsyncMock()

    @provide(scope=Scope.APP)
    def provide_organization_settings(self) -> OrganizationSettings:
        return OrganizationSettings()


@pytest.mark.parametrize(
    ("organizations_provider", "bindings"),
    [
        pytest.param(OrganizationsWebProvider, WEB_BINDINGS, id="web"),
        pytest.param(OrganizationsPublicApiProvider, PUBLIC_API_BINDINGS, id="public_api"),
    ],
)
async def test_each_entrypoints_provider_builds_todays_organizations_bindings(
    organizations_provider: type[Provider],
    bindings: Mapping[Any, type[Any]],
) -> None:
    # Exactly today's bindings, each resolving to today's class, built per request.
    container = make_async_container(organizations_provider(), FakeBaseProvider())
    async with container() as request_container:
        for port, concrete in bindings.items():
            assert isinstance(await request_container.get(port), concrete), port
    await container.close()


@pytest.mark.story("ORG.D4.IN.J1.A1")
async def test_the_public_api_provider_binds_no_organization_writes() -> None:
    # Writes stay off the public API until API keys can be scoped
    # (docs/plans/9-organizations.md, Step 15; test_container_bindings.py, ABSENT).
    container = make_async_container(OrganizationsPublicApiProvider(), FakeBaseProvider())
    async with container() as request_container:
        with pytest.raises(NoFactoryError):
            await request_container.get(OrganizationRepository)
    await container.close()
