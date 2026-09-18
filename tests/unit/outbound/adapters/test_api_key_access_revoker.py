from uuid import uuid4

import pytest

from app.core.commands.ports.api_key_repository import ApiKeyRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId
from app.outbound.adapters.api_key_access_revoker import ApiKeyAccessRevoker


class FakeApiKeyRepository(ApiKeyRepository):
    """Appends to a shared call_log so the test can assert
    revoke_all_for_user() happens BEFORE commit(), not just that both
    happen."""

    def __init__(self, call_log: list[str]) -> None:
        self._call_log = call_log
        self.revoked_for_user_id: UserId | None = None

    def add(self, api_key: ApiKey) -> None:
        raise NotImplementedError

    async def get_by_id(self, api_key_id: ApiKeyId, *, for_update: bool = False) -> ApiKey | None:
        raise NotImplementedError

    async def get_by_key_hash(self, key_hash: ApiKeyHash) -> ApiKey | None:
        raise NotImplementedError

    async def revoke_all_for_user(self, user_id: UserId) -> None:
        self._call_log.append("revoke_all_for_user")
        self.revoked_for_user_id = user_id


class FakeTransactionManager(TransactionManager):
    def __init__(self, call_log: list[str]) -> None:
        self._call_log = call_log

    async def commit(self) -> None:
        self._call_log.append("commit")


@pytest.mark.asyncio
async def test_revokes_all_keys_then_commits_in_order() -> None:
    call_log: list[str] = []
    user_id = UserId(uuid4())
    api_key_repository = FakeApiKeyRepository(call_log)
    sut = ApiKeyAccessRevoker(
        api_key_repository=api_key_repository,
        transaction_manager=FakeTransactionManager(call_log),
    )

    await sut.remove_all_user_access(user_id)

    assert call_log == ["revoke_all_for_user", "commit"]
    assert api_key_repository.revoked_for_user_id == user_id
