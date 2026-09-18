from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.entities.types_ import UserId
from app.core.common.ports.access_revoker import AccessRevoker


class ApiKeyAccessRevoker(AccessRevoker):
    """
    Today's AuthSessionAccessRevoker only revokes sessions; by the same
    symmetry, this one only revokes API keys. CurrentUserService calls
    whichever concrete AccessRevoker the current container binds when the
    resolved user turns out to be missing/inactive, and ChangeOwnPassword
    calls it directly too (see the plan's "Symmetric profile access"/
    ChangeOwnPassword sections).
    """

    def __init__(self, api_key_repository: ApiKeyRepository, transaction_manager: TransactionManager) -> None:
        self._api_key_repository = api_key_repository
        self._transaction_manager = transaction_manager

    async def remove_all_user_access(self, user_id: UserId) -> None:
        await self._api_key_repository.revoke_all_for_user(user_id)
        await self._transaction_manager.commit()
