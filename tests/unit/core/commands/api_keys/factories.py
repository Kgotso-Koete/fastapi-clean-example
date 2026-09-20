from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId
from app.core.common.entities.user import User
from app.core.common.ports.api_key_hasher import ApiKeyHasher
from app.core.common.ports.user_finder import UserFinder
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.core.queries.ports.api_key_reader import ApiKeyReader, ApiKeyUsageStatsQm, ListApiKeysQm
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingParams

# Shared fakes for every core/commands/api_keys/*.py unit test (IssueApiKey,
# RevokeApiKey, ChangeOwnPassword, ...) -- unlike the file-local fakes in
# e.g. tests/unit/outbound/adapters/test_api_key_identity_provider.py,
# these genuinely are reused across multiple test files, matching the
# plan's own Package layout section.


class FakeUserFinder(UserFinder):
    """Returns a fixed user (or None), regardless of the username/email
    asked for -- mirrors CliIdentityProvider's own test fake. Records every
    call so a test can assert which lookup method the caller actually used
    (e.g. proving an email-shaped identifier really goes through
    find_by_email, not just "some lookup returned a user")."""

    def __init__(self, user: User | None) -> None:
        self._user = user
        self.find_by_username_calls: list[Username] = []
        self.find_by_email_calls: list[Email] = []

    async def find_by_username(self, username: Username) -> User | None:
        self.find_by_username_calls.append(username)
        return self._user

    async def find_by_email(self, email: Email) -> User | None:
        self.find_by_email_calls.append(email)
        return self._user


class FakeApiKeyHasher(ApiKeyHasher):
    """Deterministic but obviously fake -- tags the raw key rather than
    actually hashing it, so a test can assert the repository received
    something OTHER than the raw key, without depending on the real
    algorithm (already covered by test_hmac_sha256_api_key_hasher.py)."""

    def hash(self, raw_key: str) -> ApiKeyHash:
        return ApiKeyHash(f"hashed:{raw_key}")


class FakeUtcTimer(UtcTimer):
    def __init__(self, now: UtcDatetime) -> None:
        self._now = now

    @property
    def now(self) -> UtcDatetime:
        return self._now


class FakeApiKeyRepository(ApiKeyRepository):
    """Records every ApiKey passed to add() for later assertions, and
    returns a fixed get_by_id() result (RevokeApiKey/GetApiKeyUsageStats
    need this; IssueApiKey's own tests only ever exercise add()).
    get_by_key_hash()/revoke_all_for_user() aren't needed by any test using
    this fake yet -- raising NotImplementedError makes an accidental,
    unexpected call to one of them fail loudly instead of silently
    returning None. count_active_for_user() returns a fixed count
    (defaulting to 0, i.e. "well under any limit") and records every user_id
    it was asked about, for IssueApiKey's key-limit tests."""

    def __init__(self, get_by_id_result: ApiKey | None = None, count_active_for_user_result: int = 0) -> None:
        self.added: list[ApiKey] = []
        self._get_by_id_result = get_by_id_result
        self._count_active_for_user_result = count_active_for_user_result
        self.count_active_for_user_calls: list[UserId] = []

    def add(self, api_key: ApiKey) -> None:
        self.added.append(api_key)

    async def get_by_id(self, api_key_id: ApiKeyId, *, for_update: bool = False) -> ApiKey | None:
        return self._get_by_id_result

    async def get_by_key_hash(self, key_hash: ApiKeyHash) -> ApiKey | None:
        raise NotImplementedError

    async def revoke_all_for_user(self, user_id: UserId) -> None:
        raise NotImplementedError

    async def count_active_for_user(self, user_id: UserId) -> int:
        self.count_active_for_user_calls.append(user_id)
        return self._count_active_for_user_result


class FakeTransactionManager(TransactionManager):
    def __init__(self) -> None:
        self.commit_call_count = 0

    async def commit(self) -> None:
        self.commit_call_count += 1


class FakeApiKeyReader(ApiKeyReader):
    """Records every list_by_user() call's args for later assertions, and
    returns a fixed result regardless of what's asked for -- query-side,
    but kept in this same shared file per the plan's own Package layout,
    since it's just as reusable across api_keys query tests (ListApiKeys,
    GetApiKeyUsageStats) as the command-side fakes above are."""

    def __init__(
        self,
        list_result: ListApiKeysQm | None = None,
        usage_stats_result: ApiKeyUsageStatsQm | None = None,
    ) -> None:
        self._list_result = list_result or ListApiKeysQm(api_keys=[], total=0, limit=0, offset=0)
        self._usage_stats_result = usage_stats_result
        self.list_by_user_calls: list[tuple[UserId, OffsetPaginationParams, SortingParams]] = []

    async def list_by_user(
        self,
        user_id: UserId,
        *,
        pagination: OffsetPaginationParams,
        sorting: SortingParams,
    ) -> ListApiKeysQm:
        self.list_by_user_calls.append((user_id, pagination, sorting))
        return self._list_result

    async def get_usage_stats_by_id(self, api_key_id: ApiKeyId) -> ApiKeyUsageStatsQm | None:
        return self._usage_stats_result
