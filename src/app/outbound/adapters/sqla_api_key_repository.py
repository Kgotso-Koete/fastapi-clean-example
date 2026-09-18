from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.outbound.exceptions import StorageError
from app.outbound.persistence_sqla.mappings.api_key import api_keys_table


class SqlaApiKeyRepository(ApiKeyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, api_key: ApiKey) -> None:
        try:
            self._session.add(api_key)
        except SQLAlchemyError as e:
            raise StorageError from e

    async def get_by_id(self, api_key_id: ApiKeyId, *, for_update: bool = False) -> ApiKey | None:
        try:
            return await self._session.get(
                ApiKey,
                api_key_id,
                with_for_update=for_update,
            )
        except SQLAlchemyError as e:
            raise StorageError from e

    async def get_by_key_hash(self, key_hash: ApiKeyHash) -> ApiKey | None:
        # A direct ORM select (not the raw table), mirroring
        # SqlaUserFinder.find_by_username() -- the returned ApiKey is a
        # tracked entity through the session's identity map, so
        # ApiKeyIdentityProvider's subsequent api_key.record_use(...) +
        # commit() persists correctly.
        stmt = select(ApiKey).where(api_keys_table.c.key_hash == key_hash)
        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as e:
            raise StorageError from e
        return result.scalar_one_or_none()

    async def revoke_all_for_user(self, user_id: UserId) -> None:
        # A load-then-mutate loop, NOT a bulk UPDATE -- deliberately, after
        # three separate real bugs surfaced trying to make a bulk Core-level
        # UPDATE stay consistent with whatever ApiKey objects already
        # happen to be loaded in this same session (a stale in-memory
        # object; then a MissingGreenlet crash from an expired attribute on
        # an AsyncSession; then an UnevaluatableError from WHERE-clause
        # columns lacking the ORM annotations synchronize_session="evaluate"
        # needs). See the plan's Step 3 notes for the full story of why
        # each attempt failed. Loading this user's own un-revoked keys
        # (realistically a handful at this deployment's scale, never
        # thousands) and calling the same already-tested revoke() on each
        # sidesteps the entire class of problem: there is only ever one
        # copy of each key's state -- the loaded ORM object itself -- so
        # there is nothing to keep synchronized with a separate SQL
        # statement. This also matches how every other single-entity
        # mutation in this codebase already works (load, mutate via the
        # entity's own method, commit), rather than introducing bulk-SQL
        # semantics as a one-off exception.
        now = UtcDatetime(datetime.now(UTC))
        stmt = select(ApiKey).where(api_keys_table.c.user_id == user_id).where(api_keys_table.c.revoked_at.is_(None))
        try:
            result = await self._session.execute(stmt)
            for api_key in result.scalars():
                api_key.revoke(now=now)
        except SQLAlchemyError as e:
            raise StorageError from e
