from typing import ClassVar, Final

from starlette.requests import Request

from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.entities.types_ import UserId
from app.core.common.exceptions import BaseError
from app.core.common.ports.api_key_hasher import ApiKeyHasher
from app.core.common.ports.identity_provider import IdentityProvider

API_KEY_HEADER_NAME: Final[str] = "X-API-Key"


class ApiKeyAuthenticationError(BaseError):
    default_message: ClassVar[str] = "Invalid or expired API key."


class ApiKeyIdentityProvider(IdentityProvider):
    """
    Resolves the current user from an X-API-Key header instead of a
    browser cookie session -- mirrors AuthSessionIdentityProvider's shape
    but with a much shorter dependency chain (no CookieManager/AuthService/
    JwtProcessor). ApiKeyAuthenticationError is defined right here, exactly
    like CliIdentityError lives directly inside main/cli/identity_provider.py --
    keeps the whole mechanism in one small, self-contained, deletable file.
    """

    def __init__(
        self,
        request: Request,
        api_key_repository: ApiKeyRepository,
        api_key_hasher: ApiKeyHasher,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
    ) -> None:
        self._request = request
        self._api_key_repository = api_key_repository
        self._api_key_hasher = api_key_hasher
        self._utc_timer = utc_timer
        self._transaction_manager = transaction_manager

    async def get_current_user_id(self) -> UserId:
        raw_key = self._request.headers.get(API_KEY_HEADER_NAME)
        if not raw_key:
            raise ApiKeyAuthenticationError
        key_hash = self._api_key_hasher.hash(raw_key)
        api_key = await self._api_key_repository.get_by_key_hash(key_hash)
        if api_key is None or api_key.is_revoked or api_key.is_expired(self._utc_timer.now):
            raise ApiKeyAuthenticationError

        # Usage-analytics footprint: a plain counter/timestamp bump on the
        # same row that just authenticated, committed inline -- deliberately
        # not a domain event, since nothing outside ApiKey's own boundary
        # needs to know. See docs/plans/8-public-api-key-auth.md's "Usage
        # analytics" section for the full rationale, and why this adapter
        # needs a TransactionManager at all (it didn't, before that
        # addition).
        api_key.record_use(now=self._utc_timer.now)
        await self._transaction_manager.commit()
        return api_key.user_id
