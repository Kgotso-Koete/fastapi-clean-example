from typing import Any

from sqlalchemy import ColumnElement, Select, Table, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.queries.ports.organization_reader import (
    InvitationQm,
    ListMyInvitationsQm,
    ListMyOrganizationsQm,
    ListOrganizationMembersQm,
    OrganizationMemberQm,
    OrganizationQm,
    OrganizationReader,
)
from app.core.queries.query_support.exceptions import SortingError
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams
from app.outbound.exceptions import ReaderError
from app.outbound.persistence_sqla.mappings.organization import organizations_table
from app.outbound.persistence_sqla.mappings.organization_membership import organization_memberships_table
from app.outbound.persistence_sqla.mappings.user import users_table

_organizations = organizations_table
_memberships = organization_memberships_table


def _order_by(table: Table, sorting: SortingParams) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    # Same shape as SqlaApiKeyReader.list_by_user(): sort by the requested
    # column of `table`, with its id as a stable tie-breaker so pagination
    # never shuffles rows that share a sort value.
    sorting_column = table.c.get(sorting.field)
    if sorting_column is None:
        raise SortingError("Invalid sorting field")
    id_column = table.c.id
    if sorting.order == SortingOrder.ASC:
        return sorting_column.asc(), id_column.asc()
    return sorting_column.desc(), id_column.desc()


class SqlaOrganizationReader(OrganizationReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fetch_page(
        self,
        stmt: Select[Any],
        total_stmt: Select[Any],
    ) -> tuple[list[Any], int]:
        # The page's rows carry the full matching total via a
        # count(*) OVER () window column, exactly like SqlaApiKeyReader. An
        # EMPTY page carries no rows to read it from, so only then is the
        # separate COUNT query run -- same fallback as SqlaApiKeyReader.
        try:
            rows = list((await self._session.execute(stmt)).all())
            if rows:
                return rows, rows[0].total
            return rows, int(await self._session.scalar(total_stmt) or 0)
        except SQLAlchemyError as e:
            raise ReaderError from e

    async def list_for_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListMyOrganizationsQm:
        # A correlated sub-select counting each organization's ACCEPTED
        # memberships -- computed in the database with COUNT, never by
        # loading every membership row. A separate alias of the memberships
        # table, because the outer query already joins it for the caller's
        # own row.
        counted = _memberships.alias("counted")
        member_count = (
            select(func.count())
            .select_from(counted)
            .where(counted.c.organization_id == _organizations.c.id)
            .where(counted.c.accepted_at.is_not(None))
            .scalar_subquery()
        )
        # Only the caller's ACCEPTED membership qualifies an organization --
        # a pending invite is listed by list_invitations_for_user instead.
        from_clause = _organizations.join(_memberships, _memberships.c.organization_id == _organizations.c.id)
        conditions = (_memberships.c.user_id == user_id, _memberships.c.accepted_at.is_not(None))
        stmt = (
            select(
                _organizations.c.id,
                _organizations.c.name,
                _organizations.c.created_at,
                _memberships.c.role,
                member_count.label("member_count"),
                func.count().over().label("total"),
            )
            .select_from(from_clause)
            .where(*conditions)
            .order_by(*_order_by(_organizations, sorting))
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        total_stmt = select(func.count()).select_from(from_clause).where(*conditions)

        rows, total = await self._fetch_page(stmt, total_stmt)
        return ListMyOrganizationsQm(
            organizations=[
                OrganizationQm(
                    id=row.id,
                    name=row.name,
                    role=row.role,
                    member_count=row.member_count,
                    created_at=row.created_at,
                )
                for row in rows
            ],
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    async def list_members(
        self,
        organization_id: OrganizationId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListOrganizationMembersQm:
        # Joined to users ONLY for username -- email/phone are never selected.
        from_clause = _memberships.join(users_table, users_table.c.id == _memberships.c.user_id)
        condition = _memberships.c.organization_id == organization_id
        stmt = (
            select(
                _memberships.c.id,
                users_table.c.username,
                _memberships.c.role,
                _memberships.c.accepted_at,
                _memberships.c.expires_at,
                _memberships.c.created_at,
                func.count().over().label("total"),
            )
            .select_from(from_clause)
            .where(condition)
            .order_by(*_order_by(_memberships, sorting))
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        total_stmt = select(func.count()).select_from(_memberships).where(condition)
        # The organization's own member count, independent of which page is
        # being returned -- so it's the same on every page.
        member_count_stmt = (
            select(func.count())
            .select_from(_memberships)
            .where(condition)
            .where(_memberships.c.accepted_at.is_not(None))
        )

        rows, total = await self._fetch_page(stmt, total_stmt)
        try:
            member_count = int(await self._session.scalar(member_count_stmt) or 0)
        except SQLAlchemyError as e:
            raise ReaderError from e
        return ListOrganizationMembersQm(
            members=[
                OrganizationMemberQm(
                    membership_id=row.id,
                    username=row.username,
                    role=row.role,
                    accepted_at=row.accepted_at,
                    expires_at=row.expires_at,
                    created_at=row.created_at,
                )
                for row in rows
            ],
            member_count=member_count,
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    async def list_invitations_for_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListMyInvitationsQm:
        # users is joined as the INVITER (via invited_by_user_id), purely for
        # their username -- the invitee is the caller themselves.
        inviter = users_table.alias("inviter")
        from_clause = _memberships.join(_organizations, _organizations.c.id == _memberships.c.organization_id).join(
            inviter, inviter.c.id == _memberships.c.invited_by_user_id
        )
        # Only the caller's own, still-PENDING, UNEXPIRED rows -- an accepted
        # row is a membership (list_for_user), not an invitation, and an
        # expired one can no longer be accepted. Expiry is compared against
        # the database's own clock (now()), since the query side has no
        # UtcTimer of its own.
        conditions = (
            _memberships.c.user_id == user_id,
            _memberships.c.accepted_at.is_(None),
            _memberships.c.expires_at > func.now(),
        )
        stmt = (
            select(
                _memberships.c.id,
                _memberships.c.organization_id,
                _organizations.c.name.label("organization_name"),
                _memberships.c.role,
                inviter.c.username.label("invited_by_username"),
                _memberships.c.created_at,
                _memberships.c.expires_at,
                func.count().over().label("total"),
            )
            .select_from(from_clause)
            .where(*conditions)
            .order_by(*_order_by(_memberships, sorting))
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        total_stmt = select(func.count()).select_from(_memberships).where(*conditions)

        rows, total = await self._fetch_page(stmt, total_stmt)
        return ListMyInvitationsQm(
            invitations=[
                InvitationQm(
                    membership_id=row.id,
                    organization_id=row.organization_id,
                    organization_name=row.organization_name,
                    role=row.role,
                    invited_by_username=row.invited_by_username,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                )
                for row in rows
            ],
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
        )
