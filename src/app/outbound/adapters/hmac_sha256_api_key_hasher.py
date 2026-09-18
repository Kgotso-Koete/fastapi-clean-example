import hashlib
import hmac

from app.core.common.entities.api_key import ApiKeyHash
from app.core.common.ports.api_key_hasher import ApiKeyHasher

# Domain-separates the sub-key this hasher actually uses from the raw
# PasswordHasherSettings.PEPPER value -- standard key-separation hygiene,
# so this feature never reuses the exact same secret bytes another hasher
# (BcryptPasswordHasher) also derives from, even though both start from
# the same top-level pepper setting.
_DOMAIN_SEPARATOR = b"api-key-v1"


class HmacSha256ApiKeyHasher(ApiKeyHasher):
    """
    Deterministic, unsalted HMAC-SHA256 over a raw API key. Deliberately
    not bcrypt: a generated raw key already carries 256 bits of `secrets`-
    sourced entropy, far beyond what a slow KDF meaningfully protects
    against, and a deterministic hash is what makes an O(1)
    `WHERE key_hash = :hash` lookup possible at all (bcrypt's per-call
    salt would force an O(n) scan instead). See the plan's "key-hashing
    decision" section for the full rationale.
    """

    def __init__(self, pepper: bytes) -> None:
        # Derived once per instance, not per call -- hash() runs on every
        # authenticated request, so this avoids repeating the subkey
        # derivation on every single call.
        self._subkey = hmac.new(key=pepper, msg=_DOMAIN_SEPARATOR, digestmod=hashlib.sha256).digest()

    def hash(self, raw_key: str) -> ApiKeyHash:
        digest = hmac.new(key=self._subkey, msg=raw_key.encode(), digestmod=hashlib.sha256).hexdigest()
        return ApiKeyHash(digest)
