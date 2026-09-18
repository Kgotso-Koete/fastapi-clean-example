import logging
from dataclasses import dataclass
from uuid import UUID

from app.core.commands.api_key_exceptions import ApiKeyNotFoundError
from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.entities.api_key import ApiKeyId

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RevokeApiKeyRequest:
    api_key_id: UUID


class RevokeApiKey:
    """
    - Open to any authenticated caller.
    - Revokes ONE of the caller's own API keys, by id.
    - A plain ownership check (api_key.user_id != current_user.id_), not a
      Permission/authorize() call -- the plan deliberately reuses the
      existing, shared AuthorizationError unmodified rather than adding a
      new Permission class for what is just an equality check.
    - Idempotent: revoking an already-revoked key is a silent no-op (no
      second commit), so retrying a DELETE that already succeeded is safe.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        api_key_repository: ApiKeyRepository,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_user_service = current_user_service
        self._api_key_repository = api_key_repository
        self._utc_timer = utc_timer
        self._transaction_manager = transaction_manager

    async def execute(self, request: RevokeApiKeyRequest) -> None:
        logger.info("Revoke API key: started.")

        current_user = await self._current_user_service.get_current_user()
        api_key_id = ApiKeyId(request.api_key_id)
        api_key = await self._api_key_repository.get_by_id(api_key_id, for_update=True)
        if api_key is None:
            raise ApiKeyNotFoundError

        # Ownership check happens BEFORE any mutation -- a caller probing
        # another user's key id must never be able to revoke it, even as
        # a side effect of an otherwise-rejected request.
        if api_key.user_id != current_user.id_:
            raise AuthorizationError

        if not api_key.is_revoked:
            api_key.revoke(now=self._utc_timer.now)
            await self._transaction_manager.commit()

        logger.info("Revoke API key: done.")
