from app.core.common.entities.types_ import UserId
from app.core.common.ports.access_revoker import AccessRevoker
from app.outbound.auth_ctx.sqla_transaction_manager import AuthSqlaTransactionManager
from app.outbound.auth_ctx.sqla_tx_storage import AuthSessionSqlaTxStorage


class CliAccessRevoker(AccessRevoker):
    """
    CoreProvider's AccessRevoker binding (AuthSessionAccessRevoker) goes
    through AuthService, which needs CookieManager, which needs a real
    Starlette Request -- the exact same trap identity_provider had (see
    docs/plans/6-inbound-cli.md). But the only thing AccessRevoker actually
    does, deleting a user's AuthSession rows, doesn't need AuthService at
    all: AuthService.revoke_all_sessions() itself only touches
    AuthSessionSqlaTxStorage/AuthSqlaTransactionManager, both Request-free.
    This talks to those two directly instead.
    """

    def __init__(
        self,
        session_tx_storage: AuthSessionSqlaTxStorage,
        transaction_manager: AuthSqlaTransactionManager,
    ) -> None:
        self._session_tx_storage = session_tx_storage
        self._transaction_manager = transaction_manager

    async def remove_all_user_access(self, user_id: UserId) -> None:
        await self._session_tx_storage.delete_all_for_user(user_id)
        await self._transaction_manager.commit()
