from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.common.entities.organization import Organization, OrganizationId
from app.core.common.entities.organization_membership import (
    OrganizationMembership,
    OrganizationMembershipId,
    OrganizationRole,
)
from app.core.common.entities.types_ import UserId
from app.outbound.exceptions import StorageError
from app.outbound.persistence_sqla.mappings.organization_membership import organization_memberships_table
from app.outbound.persistence_sqla.mappings.user import users_table


class SqlaOrganizationRepository(OrganizationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, organization: Organization) -> None:
        try:
            self._session.add(organization)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def get_by_id(self, organization_id: OrganizationId) -> Organization | None:
        try:
            return await self._session.get(Organization, organization_id)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def delete(self, organization: Organization) -> None:
        # Staged like delete_membership(): the DELETE runs on the caller's
        # commit. There's no SQLAlchemy relationship() to memberships, so this
        # is the only statement sent -- Postgres's ON DELETE CASCADE on
        # organization_memberships.organization_id removes every membership
        # and invitation in the same statement.
        try:
            await self._session.delete(organization)
        except SQLAlchemyError as e:
            raise StorageError from e

    def add_membership(self, membership: OrganizationMembership) -> None:
        try:
            self._session.add(membership)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def get_membership_by_id(
        self,
        organization_id: OrganizationId,
        membership_id: OrganizationMembershipId,
    ) -> OrganizationMembership | None:
        # A direct ORM select (not session.get()), because session.get() can
        # only look up by primary key -- and the whole point here is the
        # extra organization_id condition. The returned membership is still a
        # tracked entity, so a caller's mutation + commit() persists.
        stmt = (
            select(OrganizationMembership)
            .where(organization_memberships_table.c.id == membership_id)
            .where(organization_memberships_table.c.organization_id == organization_id)
        )
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return result.scalar_one_or_none()

    async def get_membership_for_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> OrganizationMembership | None:
        # Same shape as get_membership_by_id() above, keyed on the user
        # instead of the membership id. Both conditions matter: a row in a
        # DIFFERENT organization must never count. scalar_one_or_none() is
        # safe because the unique (organization_id, user_id) constraint
        # guarantees at most one row.
        stmt = (
            select(OrganizationMembership)
            .where(organization_memberships_table.c.organization_id == organization_id)
            .where(organization_memberships_table.c.user_id == user_id)
        )
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return result.scalar_one_or_none()

    async def delete_membership(self, membership: OrganizationMembership) -> None:
        # AsyncSession.delete() only STAGES the DELETE (it's async because it
        # may need to load relationships first); the row disappears when the
        # caller's transaction commits, exactly like add_membership().
        try:
            await self._session.delete(membership)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def count_owners(self, organization_id: OrganizationId) -> int:
        # A plain read-only COUNT, like SqlaApiKeyRepository.count_active_for_user().
        # accepted_at IS NOT NULL excludes pending OWNER invitations, and the
        # join to users excludes owners whose account is deactivated: they
        # can't log in, so they can't run the organization, and counting them
        # would let the last ACTIVE owner leave or be demoted.
        stmt = (
            select(func.count())
            .select_from(organization_memberships_table)
            .join(users_table, users_table.c.id == organization_memberships_table.c.user_id)
            .where(organization_memberships_table.c.organization_id == organization_id)
            .where(organization_memberships_table.c.role == OrganizationRole.OWNER)
            .where(organization_memberships_table.c.accepted_at.is_not(None))
            .where(users_table.c.is_active.is_(True))
        )
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return result.scalar_one()
