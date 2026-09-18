from datetime import datetime
from typing import NewType
from uuid import UUID

from app.core.common.entities.base import Entity
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime

# NewTypes live alongside their entity, exactly like SessionId lives
# alongside AuthSession in src/app/outbound/auth_ctx/model.py.
ApiKeyId = NewType("ApiKeyId", UUID)
ApiKeyHash = NewType("ApiKeyHash", str)  # hex digest of a raw key -- never the raw key itself


class ApiKey(Entity[ApiKeyId]):
    """
    A long-lived credential a user issues (via username/password) to
    authenticate programmatic, server-to-server requests instead of a
    browser cookie session. Only `key_hash` is ever persisted; the raw
    key itself is shown to the caller exactly once, at issuance.
    """

    def __init__(
        self,
        *,
        id_: ApiKeyId,
        user_id: UserId,
        key_hash: ApiKeyHash,
        key_prefix: str,
        label: str | None,
        created_at: UtcDatetime,
        expires_at: UtcDatetime,
        revoked_at: UtcDatetime | None = None,
        use_count: int = 0,
        last_used_at: UtcDatetime | None = None,
    ) -> None:
        super().__init__(id_=id_)
        self.user_id = user_id
        self.key_hash = key_hash
        # Non-secret, stored in the clear -- lets a "list my keys" response
        # show e.g. "ak_a1b2c3d4..." so a caller can tell keys apart
        # without the raw key ever being persisted or shown again.
        self.key_prefix = key_prefix
        self.label = label
        self._created_at = created_at
        self.expires_at = expires_at
        # revoked_at/last_used_at go through the property setters below,
        # NOT a SQLAlchemy composite() like created_at/expires_at -- see
        # their docstrings for why a nullable UtcDatetime specifically
        # can't use composite() cleanly in this SQLAlchemy version.
        self.revoked_at = revoked_at
        # Usage-analytics footprint: a plain counter/timestamp on this same
        # aggregate, bumped by record_use() below. Deliberately not a
        # domain event -- the side effect never leaves ApiKey's own
        # consistency boundary, so raising/staging/dispatching an event
        # just to increment a field on the row that raised it would be the
        # wrong-sized tool. See docs/plans/8-public-api-key-auth.md's
        # "Usage analytics" section for the full rationale.
        self.use_count = use_count
        self.last_used_at = last_used_at

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at

    @property
    def revoked_at(self) -> UtcDatetime | None:
        """
        Backed by _revoked_at, a plain nullable `datetime` column (see the
        mapping) -- not a composite(UtcDatetime, ...) like created_at/
        expires_at. A composite's read path unconditionally calls its
        class_ with the raw column value(s), which crashes UtcDatetime's
        constructor on NULL; and once worked around with a None-tolerant
        wrapper function, its WRITE path breaks instead, because
        SQLAlchemy generates a composite's column-extraction logic by
        introspecting class_ as a dataclass, which a wrapper function
        isn't. Doing the None-check here, in a plain Python property, and
        mapping the raw column directly, sidesteps composite()'s
        null-handling entirely instead of fighting it. See the plan's
        Step 3 notes for the full story.
        """
        return UtcDatetime(self._revoked_at) if self._revoked_at is not None else None

    @revoked_at.setter
    def revoked_at(self, value: UtcDatetime | None) -> None:
        self._revoked_at: datetime | None = value.value if value is not None else None

    @property
    def is_revoked(self) -> bool:
        return self._revoked_at is not None

    def is_expired(self, now: UtcDatetime) -> bool:
        return now.value >= self.expires_at.value

    def revoke(self, *, now: UtcDatetime) -> None:
        self.revoked_at = now

    @property
    def last_used_at(self) -> UtcDatetime | None:
        """Same reasoning as revoked_at's property above -- backed by the
        plain nullable _last_used_at column, not a composite()."""
        return UtcDatetime(self._last_used_at) if self._last_used_at is not None else None

    @last_used_at.setter
    def last_used_at(self, value: UtcDatetime | None) -> None:
        self._last_used_at: datetime | None = value.value if value is not None else None

    def record_use(self, *, now: UtcDatetime) -> None:
        """Called by ApiKeyIdentityProvider immediately after this key
        successfully authenticates a request (never on a failed one)."""
        self.use_count += 1
        self.last_used_at = now
