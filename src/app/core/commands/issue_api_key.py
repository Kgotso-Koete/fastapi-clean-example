from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict
from uuid import UUID

from app.core.commands.api_key_exceptions import (
    API_KEY_ACCOUNT_INACTIVE,
    ApiKeyLimitExceededError,
    InvalidApiKeyCredentialsError,
)
from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.entities.api_key import ApiKey
from app.core.common.factories.api_key_id_factory import create_api_key_id
from app.core.common.factories.raw_api_key_factory import generate_raw_api_key
from app.core.common.ports.api_key_hasher import ApiKeyHasher
from app.core.common.ports.user_finder import UserFinder
from app.core.common.services.user import UserService
from app.core.common.value_objects.api_key_expiry_days import ApiKeyExpiryDays
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.identifier import resolve_username_or_email
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.utc_datetime import UtcDatetime


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueApiKeyRequest:
    identifier: str
    password: str
    expires_in_days: int
    label: str | None = None


class IssueApiKeyResponse(TypedDict):
    id: UUID
    raw_key: str  # shown exactly once -- never persisted, never returned again
    label: str | None
    created_at: datetime
    expires_at: datetime


class IssueApiKey:
    """
    - Open to everyone with valid credentials for an active account.
    - Mirrors LogIn's verify-credentials shape, but issues a long-lived API
      key instead of a cookie session.
    - Deliberate difference from LogIn: does not check "already
      authenticated" -- minting an additional key while another key/session
      is already valid is the normal case (like GitHub/Stripe letting you
      mint additional PATs from an already-logged-in dashboard), not a
      corner case to block.
    """

    def __init__(
        self,
        user_finder: UserFinder,
        user_service: UserService,
        utc_timer: UtcTimer,
        api_key_hasher: ApiKeyHasher,
        api_key_repository: ApiKeyRepository,
        transaction_manager: TransactionManager,
        max_keys_per_user: int,
    ) -> None:
        self._user_finder = user_finder
        self._user_service = user_service
        self._utc_timer = utc_timer
        self._api_key_hasher = api_key_hasher
        self._api_key_repository = api_key_repository
        self._transaction_manager = transaction_manager
        self._max_keys_per_user = max_keys_per_user

    async def execute(self, request: IssueApiKeyRequest) -> IssueApiKeyResponse:
        identifier = resolve_username_or_email(request.identifier)
        if isinstance(identifier, Email):
            user = await self._user_finder.find_by_email(identifier)
        else:
            user = await self._user_finder.find_by_username(identifier)
        # Same error for "no such user" and "wrong password" -- a different
        # message per case would let a caller enumerate valid usernames.
        if user is None or not await self._user_service.is_password_valid(user, RawPassword(request.password)):
            raise InvalidApiKeyCredentialsError
        if not user.is_active:
            raise InvalidApiKeyCredentialsError(API_KEY_ACCOUNT_INACTIVE)

        # Also BEFORE generating/persisting anything, same discipline as the
        # expiry check below -- counts only active (non-revoked) keys, so
        # revoking an old key frees up a slot rather than being a lifetime cap.
        active_key_count = await self._api_key_repository.count_active_for_user(user.id_)
        if active_key_count >= self._max_keys_per_user:
            raise ApiKeyLimitExceededError

        # Validate the caller-chosen expiry BEFORE generating/persisting
        # anything -- an out-of-range value must never leave a raw key
        # generated (even one that's then discarded) or a partial write.
        expiry_days = ApiKeyExpiryDays(request.expires_in_days)
        now = self._utc_timer.now
        expires_at = UtcDatetime(now.value + timedelta(days=expiry_days.value))

        raw_key = generate_raw_api_key()
        api_key = ApiKey(
            id_=create_api_key_id(),
            user_id=user.id_,
            key_hash=self._api_key_hasher.hash(raw_key),
            # "ak_" + 8 chars -- non-secret, display-only. See ApiKey.key_prefix's own docstring.
            key_prefix=raw_key[:11],
            label=request.label,
            created_at=now,
            expires_at=expires_at,
        )
        self._api_key_repository.add(api_key)
        await self._transaction_manager.commit()
        return IssueApiKeyResponse(
            id=api_key.id_,
            raw_key=raw_key,
            label=api_key.label,
            created_at=now.value,
            expires_at=expires_at.value,
        )
