import pytest

from app.core.common.authorization.current_organization_service import CurrentOrganizationService
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.common.authorization.organization_ports import MembershipChecker
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.entities.types_ import UserId
from app.core.common.factories.organization_id_factory import create_organization_id
from tests.unit.core.common.authorization.factories import (
    FakeAccessRevoker,
    FakeAuthzUserFinder,
    FakeIdentityProvider,
    FakeRowSecurityContext,
    create_current_user_service,
)
from tests.unit.core.common.services.factories import create_user

# CurrentOrganizationService is the one place an organization-scoped use case
# asks "is the current user allowed in THIS organization, at THIS level?".
# It resolves the current user, looks up their role via MembershipChecker
# (async, so BEFORE authorize()), then lets the synchronous
# CanAccessOrganization decide.


class FakeMembershipChecker(MembershipChecker):
    """Returns a fixed role (or None) and records every lookup it's asked
    for, so a test can assert on WHO was checked in WHICH organization. An
    optional shared `log` also records the lookup alongside another fake's
    entries (FakeRowSecurityContext's binds), so their order can be checked."""

    def __init__(self, role: OrganizationRole | None, log: list[tuple[str, object]] | None = None) -> None:
        self._role = role
        self._log = log
        self.calls: list[tuple[UserId, OrganizationId]] = []

    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        self.calls.append((user_id, organization_id))
        if self._log is not None:
            self._log.append(("get_role", (user_id, organization_id)))
        return self._role


@pytest.mark.asyncio
async def test_a_member_meeting_the_minimum_role_gets_the_organization_id_and_current_user_back() -> None:
    user = create_user()
    organization_id = create_organization_id()
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=FakeMembershipChecker(OrganizationRole.ADMIN),
        row_security_context=FakeRowSecurityContext(),
    )

    result = await sut.require_role(organization_id, OrganizationRole.ADMIN)

    assert result == (organization_id, user)


@pytest.mark.asyncio
async def test_a_member_below_the_minimum_role_is_denied() -> None:
    user = create_user()
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=FakeMembershipChecker(OrganizationRole.MEMBER),
        row_security_context=FakeRowSecurityContext(),
    )

    with pytest.raises(AuthorizationError):
        await sut.require_role(create_organization_id(), OrganizationRole.ADMIN)


@pytest.mark.asyncio
async def test_a_non_member_is_told_the_organization_does_not_exist() -> None:
    # None covers a non-member, a pending invitee, and a member of another
    # organization alike -- see MembershipChecker.get_role()'s contract.
    # They get "not found" (HTTP 404), NOT AuthorizationError (403): an
    # outsider must not be able to confirm the organization even exists.
    # Only a real member with too low a role gets 403 (test above).
    user = create_user()
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=FakeMembershipChecker(None),
        row_security_context=FakeRowSecurityContext(),
    )

    with pytest.raises(OrganizationNotFoundError):
        await sut.require_role(create_organization_id(), OrganizationRole.MEMBER)


@pytest.mark.asyncio
async def test_the_membership_lookup_uses_the_current_users_id_and_the_given_organization_id() -> None:
    # Guards against checking the wrong user or the wrong organization --
    # either would make the answer meaningless while still "passing".
    user = create_user()
    organization_id = create_organization_id()
    membership_checker = FakeMembershipChecker(OrganizationRole.OWNER)
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=membership_checker,
        row_security_context=FakeRowSecurityContext(),
    )

    await sut.require_role(organization_id, OrganizationRole.MEMBER)

    assert membership_checker.calls == [(user.id_, organization_id)]


@pytest.mark.asyncio
async def test_an_unresolvable_current_user_is_denied_before_any_membership_lookup() -> None:
    # A real CurrentUserService whose user lookup finds nothing (e.g. a
    # deleted or deactivated account) raises AuthorizationError itself --
    # the membership check must never even run in that case.
    user = create_user()
    current_user_service = CurrentUserService(
        identity_provider=FakeIdentityProvider(user.id_),
        authz_user_finder=FakeAuthzUserFinder(None),
        access_revoker=FakeAccessRevoker(),
    )
    membership_checker = FakeMembershipChecker(OrganizationRole.OWNER)
    sut = CurrentOrganizationService(
        current_user_service=current_user_service,
        membership_checker=membership_checker,
        row_security_context=FakeRowSecurityContext(),
    )

    with pytest.raises(AuthorizationError):
        await sut.require_role(create_organization_id(), OrganizationRole.MEMBER)

    assert membership_checker.calls == []


# Plan 14, "Order of work": require_role tells the database who is asking and
# for which organization, so Row-Level Security filters every query after it.


@pytest.mark.asyncio
async def test_the_user_is_bound_before_the_membership_check_and_the_organization_after_the_role_check() -> None:
    # Plan 14: the membership check runs under Row-Level Security, so it can
    # only see the caller's own row once the user is bound. The organization
    # is bound last, once the caller is known to be a member at the required
    # level: only a verified id is ever bound.
    user = create_user()
    organization_id = create_organization_id()
    log: list[tuple[str, object]] = []
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=FakeMembershipChecker(OrganizationRole.ADMIN, log=log),
        row_security_context=FakeRowSecurityContext(log),
    )

    await sut.require_role(organization_id, OrganizationRole.MEMBER)

    assert log == [
        ("bind_user", user.id_),
        ("get_role", (user.id_, organization_id)),
        ("bind_organization", organization_id),
    ]


@pytest.mark.asyncio
async def test_a_non_member_never_gets_the_organization_bound() -> None:
    user = create_user()
    context = FakeRowSecurityContext()
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=FakeMembershipChecker(None),
        row_security_context=context,
    )

    with pytest.raises(OrganizationNotFoundError):
        await sut.require_role(create_organization_id(), OrganizationRole.MEMBER)

    assert context.log == [("bind_user", user.id_)]


@pytest.mark.asyncio
async def test_a_member_below_the_minimum_role_never_gets_the_organization_bound() -> None:
    user = create_user()
    context = FakeRowSecurityContext()
    sut = CurrentOrganizationService(
        current_user_service=create_current_user_service(user),
        membership_checker=FakeMembershipChecker(OrganizationRole.MEMBER),
        row_security_context=context,
    )

    with pytest.raises(AuthorizationError):
        await sut.require_role(create_organization_id(), OrganizationRole.ADMIN)

    assert context.log == [("bind_user", user.id_)]


@pytest.mark.asyncio
async def test_an_unresolvable_current_user_gets_nothing_bound() -> None:
    # A deleted or deactivated account is refused before anything is bound.
    user = create_user()
    context = FakeRowSecurityContext()
    sut = CurrentOrganizationService(
        current_user_service=CurrentUserService(
            identity_provider=FakeIdentityProvider(user.id_),
            authz_user_finder=FakeAuthzUserFinder(None),
            access_revoker=FakeAccessRevoker(),
        ),
        membership_checker=FakeMembershipChecker(OrganizationRole.OWNER),
        row_security_context=context,
    )

    with pytest.raises(AuthorizationError):
        await sut.require_role(create_organization_id(), OrganizationRole.MEMBER)

    assert context.log == []
