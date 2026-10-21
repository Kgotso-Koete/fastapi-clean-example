from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.common.ports.row_security_context import RowSecurityContextConflictError
from app.outbound.adapters.sqla_row_security_context import SqlaRowSecurityContext

# docs/plans/14-row-level-security.md, Step 5: the RowSecurityContext adapter.
#
# The policies read two transaction-local settings. This adapter is the one
# place that sets them: it applies a bind to the open transaction straight
# away, and again at the start of every later transaction in the same
# session (after a commit). These tests read the settings back with
# current_setting; which login runs them doesn't matter here.

_ORGANIZATION: str = "app.current_organization_id"
_USER: str = "app.current_user_id"


async def _setting(session: AsyncSession, name: str) -> str | None:
    # NULL when never set on this connection; '' once a transaction that set
    # it has ended.
    result = await session.execute(text("SELECT current_setting(:name, true)"), {"name": name})
    value: str | None = result.scalar_one()
    return value


async def test_an_organization_bound_after_the_transaction_began_applies_to_that_transaction(
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # The hard case: in a real request, loading the user opens the
    # transaction before the organization is known. A design that only binds
    # when a transaction begins would bind nothing for the rest of it.
    organization_id = OrganizationId(uuid4())
    async with it_sessionmaker() as session:
        context = SqlaRowSecurityContext(session)
        await session.execute(text("SELECT 1"))
        await context.bind_organization(organization_id)

        assert await _setting(session, _ORGANIZATION) == str(organization_id)


async def test_a_user_bound_after_the_transaction_began_applies_to_that_transaction(
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = UserId(uuid4())
    async with it_sessionmaker() as session:
        context = SqlaRowSecurityContext(session)
        await session.execute(text("SELECT 1"))
        await context.bind_user(user_id)

        assert await _setting(session, _USER) == str(user_id)


async def test_a_bound_organization_is_applied_again_after_a_commit(
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # set_config(..., true) ends with its transaction; a use case that
    # commits and goes on querying must still be bound.
    organization_id = OrganizationId(uuid4())
    async with it_sessionmaker() as session:
        context = SqlaRowSecurityContext(session)
        # Bound inside the first transaction, so the check below proves the
        # bind reached the next one.
        await session.execute(text("SELECT 1"))
        await context.bind_organization(organization_id)
        await session.commit()

        assert await _setting(session, _ORGANIZATION) == str(organization_id)


async def test_another_session_sees_nothing_bound(
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # A bind belongs to one session (one request), never to the next.
    async with it_sessionmaker() as session:
        await SqlaRowSecurityContext(session).bind_organization(OrganizationId(uuid4()))
        await session.commit()

    async with it_sessionmaker() as other_session:
        SqlaRowSecurityContext(other_session)
        # NULL on a fresh connection, '' on a reused one: either way, unset.
        assert not await _setting(other_session, _ORGANIZATION)


async def test_binding_a_different_organization_in_the_same_session_raises(
    it_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # OWASP: the verified context must never be replaced mid-request.
    # Binding the same organization again is harmless; a different one is a
    # bug, and must fail loudly rather than quietly switch organizations.
    first, second = OrganizationId(uuid4()), OrganizationId(uuid4())
    async with it_sessionmaker() as session:
        context = SqlaRowSecurityContext(session)
        await context.bind_organization(first)
        await context.bind_organization(first)

        with pytest.raises(RowSecurityContextConflictError):
            await context.bind_organization(second)
