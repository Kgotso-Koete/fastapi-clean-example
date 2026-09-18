from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.api_key import ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.queries.ports.api_key_reader import ApiKeyQm, ApiKeyReader, ApiKeyUsageStatsQm, ListApiKeysQm
from app.core.queries.query_support.exceptions import SortingError
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder, SortingParams
from app.outbound.exceptions import ReaderError
from app.outbound.persistence_sqla.mappings.api_key import api_keys_table


class SqlaApiKeyReader(ApiKeyReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListApiKeysQm:
        # Structurally identical to SqlaUserReader.list_users(), scoped to
        # one user's own keys via the extra .where() clause below.
        sorting_column = api_keys_table.c.get(sorting.field)
        if sorting_column is None:
            raise SortingError("Invalid sorting field")
        order_by_expression = sorting_column.asc() if sorting.order == SortingOrder.ASC else sorting_column.desc()
        id_column = api_keys_table.c.id
        secondary_order_by = id_column.asc() if sorting.order == SortingOrder.ASC else id_column.desc()
        stmt = (
            select(
                api_keys_table.c.id,
                api_keys_table.c.key_prefix,
                api_keys_table.c.label,
                api_keys_table.c.created_at,
                api_keys_table.c.expires_at,
                api_keys_table.c.revoked_at,
                func.count().over().label("total"),
            )
            .where(api_keys_table.c.user_id == user_id)
            .order_by(order_by_expression, secondary_order_by)
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        try:
            result = await self._session.execute(stmt)
            rows = result.all()
        except SQLAlchemyError as e:
            raise ReaderError from e
        if not rows:
            total_stmt = select(func.count()).select_from(api_keys_table).where(api_keys_table.c.user_id == user_id)
            try:
                total = int(await self._session.scalar(total_stmt) or 0)
            except SQLAlchemyError as e:
                raise ReaderError from e
            return ListApiKeysQm(api_keys=[], total=total, limit=pagination.limit, offset=pagination.offset)
        api_keys = [
            ApiKeyQm(
                id=row.id,
                key_prefix=row.key_prefix,
                label=row.label,
                created_at=row.created_at,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]
        return ListApiKeysQm(
            api_keys=api_keys,
            total=rows[0].total,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    async def get_usage_stats_by_id(self, api_key_id: ApiKeyId) -> ApiKeyUsageStatsQm | None:
        # Deliberately unscoped by user_id -- see the port's own docstring
        # for why GetApiKeyUsageStats needs the raw row to check ownership
        # itself, rather than this reader silently filtering it out.
        stmt = select(
            api_keys_table.c.id,
            api_keys_table.c.user_id,
            api_keys_table.c.key_prefix,
            api_keys_table.c.label,
            api_keys_table.c.use_count,
            api_keys_table.c.last_used_at,
            api_keys_table.c.created_at,
            api_keys_table.c.expires_at,
            api_keys_table.c.revoked_at,
        ).where(api_keys_table.c.id == api_key_id)
        try:
            result = await self._session.execute(stmt)
            row = result.first()
        except SQLAlchemyError as e:
            raise ReaderError from e
        if row is None:
            return None
        return ApiKeyUsageStatsQm(
            id=row.id,
            user_id=row.user_id,
            key_prefix=row.key_prefix,
            label=row.label,
            use_count=row.use_count,
            last_used_at=row.last_used_at,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )
