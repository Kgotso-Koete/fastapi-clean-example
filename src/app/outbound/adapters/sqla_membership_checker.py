from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.authorization.organization_ports import MembershipChecker
from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.organization_membership import OrganizationRole
from app.core.common.entities.types_ import UserId
from app.outbound.exceptions import ReaderError
from app.outbound.persistence_sqla.mappings.organization_membership import organization_memberships_table


class SqlaMembershipChecker(MembershipChecker):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_role(self, user_id: UserId, organization_id: OrganizationId) -> OrganizationRole | None:
        # A plain column read, not an ORM entity load -- an authorization
        # check only needs the role, never a tracked OrganizationMembership.
        # All three conditions matter: the right user, in THIS organization
        # (a role elsewhere grants nothing here), and ACCEPTED (a pending
        # invite grants nothing yet). The unique (organization_id, user_id)
        # constraint guarantees at most one row matches.
        stmt = (
            select(organization_memberships_table.c.role)
            .where(organization_memberships_table.c.user_id == user_id)
            .where(organization_memberships_table.c.organization_id == organization_id)
            .where(organization_memberships_table.c.accepted_at.is_not(None))
        )
        try:
            role: OrganizationRole | None = await self._session.scalar(stmt)
        except SQLAlchemyError as e:
            raise ReaderError from e
        return role
