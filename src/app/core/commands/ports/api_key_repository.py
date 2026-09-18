from abc import abstractmethod
from typing import Protocol

from app.core.common.entities.api_key import ApiKey, ApiKeyHash, ApiKeyId
from app.core.common.entities.types_ import UserId


class ApiKeyRepository(Protocol):
    """Transactional: commit required."""

    @abstractmethod
    def add(self, api_key: ApiKey) -> None: ...

    @abstractmethod
    async def get_by_id(self, api_key_id: ApiKeyId, *, for_update: bool = False) -> ApiKey | None: ...

    @abstractmethod
    async def get_by_key_hash(self, key_hash: ApiKeyHash) -> ApiKey | None:
        """
        Lives on this command-side Protocol, not ApiKeyReader, because it
        IS core business-logic meaning: ApiKeyIdentityProvider (an outbound
        adapter) depends on this exact port to authenticate a request --
        a legal dependency direction, since outbound may depend on core
        ports freely. Mirrors AuthSessionIdentityProvider depending on
        AuthService.
        """
        ...

    @abstractmethod
    async def revoke_all_for_user(self, user_id: UserId) -> None:
        """Bulk-revokes every un-revoked key for one user -- used by
        ApiKeyAccessRevoker.remove_all_user_access()."""
        ...
