from typing import Final

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.common.entities.organization import OrganizationId
from app.core.common.entities.types_ import UserId
from app.core.common.ports.row_security_context import RowSecurityContext, RowSecurityContextConflictError

# The two transaction-local settings the policies read
# (persistence_sqla/row_level_security.py). The `true` makes each one last
# only until its transaction ends, so it can never leak into the next
# request on a pooled connection. Both values are bound parameters.
_SET_CONFIG: Final = text("SELECT set_config(:name, :value, true)")
_USER_SETTING: Final = "app.current_user_id"
_ORGANIZATION_SETTING: Final = "app.current_organization_id"


class SqlaRowSecurityContext(RowSecurityContext):
    """Binds the user and organization on one request's main session.

    A bind is applied twice over:
      1. straight away, if a transaction is already open: in a real request,
         loading the user opens it before the organization is known;
      2. again at the start of every later transaction in this session (after
         a commit), through an after_begin listener on this session only.
    Errors from Postgres are never caught: a failed bind must surface, not
    turn into silently empty pages.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        # Setting name -> the value bound for this request.
        self._bound: dict[str, str] = {}
        # On this one session, not on every Session class-wide, so another
        # request's session is never touched.
        event.listen(session.sync_session, "after_begin", self._apply_on_begin)

    async def bind_user(self, user_id: UserId) -> None:
        await self._bind(_USER_SETTING, str(user_id))

    async def bind_organization(self, organization_id: OrganizationId) -> None:
        await self._bind(_ORGANIZATION_SETTING, str(organization_id))

    async def _bind(self, name: str, value: str) -> None:
        already_bound = self._bound.get(name)
        if already_bound == value:
            # The same id again (two checks in one request): nothing to do.
            return
        if already_bound is not None:
            raise RowSecurityContextConflictError
        self._bound[name] = value
        if self._session.in_transaction():
            await self._session.execute(_SET_CONFIG, {"name": name, "value": value})

    def _apply_on_begin(self, _session: Session, _transaction: SessionTransaction, connection: Connection) -> None:
        # SQLAlchemy calls this, synchronously, as each new transaction begins
        # on this session's connection.
        for name, value in self._bound.items():
            connection.execute(_SET_CONFIG, {"name": name, "value": value})
