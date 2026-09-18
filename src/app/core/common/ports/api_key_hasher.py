from abc import abstractmethod
from typing import Protocol

from app.core.common.entities.api_key import ApiKeyHash


class ApiKeyHasher(Protocol):
    # No verify() -- unlike PasswordHasher, HMAC-SHA256 is deterministic,
    # so "verify" is just "hash the candidate and look it up" (an O(1)
    # `WHERE key_hash = :hash`, done by the repository, not this port).
    @abstractmethod
    def hash(self, raw_key: str) -> ApiKeyHash: ...
