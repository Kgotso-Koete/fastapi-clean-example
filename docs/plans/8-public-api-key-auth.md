# Public API with API-Key Authentication

> **Implementation Plan v0.14.0 (proposed)**
>
> Adds a second, always-documented, API-key-authenticated HTTP surface (`src/app/inbound/http/public_api/`), mounted alongside the existing cookie-session app in the same process, so a B2B customer's own backend can integrate programmatically -- issuing, listing, and revoking long-lived API keys (and changing the underlying account password) after proving username/password once -- without holding a browser cookie jar. Closes the "Public-facing API with API-key authentication" item in `docs/plans/0-production-readiness-roadmap.md` (checklist line 51, full paragraph at line 140). Modeled directly on `docs/plans/6-inbound-cli.md`, the closest analogous feature: a new non-cookie-session identity mechanism added as a fully independent module, with its own DI provider, reusing existing core ports unchanged.
>
> Explicitly **not** in scope, per the roadmap: rate limiting itself (separate, already-tracked roadmap item -- this plan only makes room for it by giving the public surface its own router group), multi-tenancy, and MFA.

## Context

This is a public-facing API for programmatic (server-to-server / "machine-to-machine") integration: a small B2B deployment (~10 employees, ~300 client integrations, ~300 orders/day) where a client's own backend calls this server directly, with no browser involved. Cookie-based session auth doesn't fit that shape at all -- there's no cookie jar on the other end. API keys (long random token, presented via header, hashed at rest, expiring) are the industry-standard, right-sized answer for this scale -- the same pattern GitHub/Stripe/SendGrid use for their own server-to-server integrations, and deliberately simpler than a full OAuth2 client-credentials flow, which only pays for itself at much larger scale with many independent auth servers. This need is already an explicit, scoped-out line item in this project's own roadmap (`docs/plans/0-production-readiness-roadmap.md`); this plan is that promised "own dedicated implementation plan."

Two decisions were confirmed directly with the user before finalizing this plan:
1. **Deployment model**: the public API is a FastAPI sub-app *mounted* into the same process as the existing app (`app.mount("/public", public_app)`), not a separate service/deployment. Simpler ops (one deploy target, no new infra) at the cost of a second DB connection pool in the same process -- an accepted, explicitly-noted tradeoff at this scale.
2. **Scope of "password management" mirroring**: the public API does include an API-key-authenticated equivalent of the existing self-service `ChangePassword`, in addition to issuing/listing/revoking keys -- not just key management alone.

A third requirement, added after the initial design pass: an authenticated account must be able to do the same self-service things whether it arrives via browser cookie (the future frontend) or via API key (a B2B backend) -- concretely, the same account must be able to retrieve its own profile through either mechanism. See "Symmetric profile access" below.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Issue a key | integrating developer | to exchange my username (or email) and password for a long-lived API key once | my backend can call this API without logging in or holding a cookie jar | `POST /public/v1/api-keys/` with `identifier`, `password`, `expires_in_days`, optional `label` returns `201` with the raw key, shown once<br>Wrong password and unknown account return the same `401`<br>`expires_in_days` outside 1 to 365 returns `400`, nothing stored |
| 2. Call the API with a key | API client | to authenticate every request with an `X-API-Key` header | I can reach my own account's data programmatically | Valid key on `GET /public/v1/account/profile/` returns `200` with the same profile the cookie app shows<br>Missing, unknown, expired or revoked key returns `401`<br>Only the key's hash is stored |
| 3. Manage my keys | account owner managing their keys | to list, inspect and revoke my own keys | I can tell them apart, see which are in use, and shut down one that leaked | `GET /public/v1/api-keys/` lists only my keys, with `key_prefix`, never a hash<br>`GET .../{api_key_id}/usage/` shows `use_count`/`last_used_at`; another account's key `403`, unknown id `404`<br>`DELETE .../{api_key_id}/` returns `204` (also when repeated); the key stops working at once |
| 4. Key limit | account owner managing their keys | a cap on how many active keys I can hold | keys can't pile up unnoticed | Holding `API_KEY_MAX_PER_USER` (default 10) non-revoked keys makes the next issue return `409`<br>Revoking a key frees a slot; not a lifetime cap |

---

## Why this is safe to add without touching existing composition

This repo already has two precedents for "a new identity mechanism, added as a wholly independent `Provider`, never by splitting or parameterizing `CoreProvider`": the Celery worker (`WorkerProvider`, `src/app/main/worker/provider.py`) and the CLI (`CliProvider`, `src/app/main/cli/provider.py`). Both exist because Dishka validates a provider set's **entire** declared dependency graph at container-build time -- a container that declares `CoreProvider`'s `identity_provider = provide(AuthSessionIdentityProvider, provides=IdentityProvider)` binding transitively needs a real Starlette `Request` (`AuthSessionIdentityProvider` → `AuthService` → `CookieManager` → `Request`), so any process/app that can't supply one must never declare that binding at all, not even indirectly.

This plan's situation is subtly different from both precedents, and that difference is the crux of the design: **the public API *is* an HTTP entrypoint, so it does have a real Starlette `Request`.** So why not just add `ApiKeyIdentityProvider` as one more binding inside `CoreProvider` and route based on which header/cookie is present? Because Dishka binds one concrete class per `Protocol` **per container**, and this repo's existing `main/run.py::make_app()` builds exactly **one** container for the whole `FastAPI` app via `main/ioc/provider_registry.py::get_providers()`. Adding a second `IdentityProvider` binding to that same container/scope would either conflict outright or silently shadow `AuthSessionIdentityProvider` -- there is no "route per-request to a different binding of the same Protocol" mechanism in this repo's Dishka usage. The correct fix, consistent with the CLI/worker precedent, is a **second, independent Dishka container**, and because Dishka's FastAPI integration (`setup_dishka(container, app)`) attaches exactly one container to `app.state.dishka_container`, a second container means a second `FastAPI` app. FastAPI supports exactly this via mounted sub-applications (`app.mount(path, sub_app)`), which is also how this feature gets its own always-on OpenAPI docs page -- one mechanism solves both requirements at once.

So: a new `PublicApiProvider` (`src/app/main/ioc/public_api.py`), a near-duplicate of `CoreProvider` for exactly the pieces the public API needs (leaner than `CoreProvider` -- no event dispatch machinery is needed at all, see below), swapping `identity_provider`/`access_revoker` to two new adapters and adding the new `ApiKey`-specific bindings, reusing `HasherThreadPoolProvider`/`PersistenceSqlaProvider`/`RequestProvider` from `src/app/main/ioc/outbound.py` verbatim -- all three are safe to reuse because none of them, nor anything `ApiKeyIdentityProvider` needs, requires the auth bounded context's cookie/JWT/session machinery (`CookieManager`, `AuthService`, `JwtProcessor`). `ApiKeyIdentityProvider` *does* need `Request` -- unlike the CLI/worker, which need none at all -- but only for one trivial line (`request.headers.get("X-API-Key")`), never for `CookieManager`/`AuthService`, which is why `RequestProvider` is reused as-is while `AuthProvider` is not.

**Deliberate deviation from a natural first guess:** it would be tempting to register `PublicApiProvider` into the *same* container as `CoreProvider` via `main/ioc/provider_registry.py::get_providers()`, the way `CeleryProvider` is added there today. That's wrong for the reason above (duplicate `IdentityProvider`/`AccessRevoker` bindings in one container) and is **not** done in this plan -- `provider_registry.py` is not touched at all. The public API gets its own container, built by its own new composition function.

**Feature-delete test:** deleting `src/app/core/common/entities/api_key.py`, `src/app/core/common/value_objects/api_key_expiry_days.py`, `src/app/core/common/ports/api_key_hasher.py`, `src/app/core/common/factories/api_key_id_factory.py`, `src/app/core/common/factories/raw_api_key_factory.py`, `src/app/core/commands/ports/api_key_repository.py`, `src/app/core/commands/api_key_exceptions.py`, `src/app/core/commands/issue_api_key.py`, `src/app/core/commands/revoke_api_key.py`, `src/app/core/queries/ports/api_key_reader.py`, `src/app/core/queries/list_api_keys.py`, `src/app/core/queries/get_api_key_usage_stats.py`, `src/app/outbound/adapters/hmac_sha256_api_key_hasher.py`, `src/app/outbound/adapters/sqla_api_key_repository.py`, `src/app/outbound/adapters/sqla_api_key_reader.py`, `src/app/outbound/adapters/api_key_identity_provider.py`, `src/app/outbound/adapters/api_key_access_revoker.py`, `src/app/outbound/persistence_sqla/mappings/api_key.py`, `src/app/main/ioc/public_api.py`, `src/app/main/run_public_api.py`, `src/app/inbound/http/public_api/**`, `src/app/core/queries/get_own_profile.py`, `src/app/inbound/http/account/profile.py`, and the one new Alembic migration, leaves `AuthProvider`, `main/run.py`, `provider_registry.py`, and every existing HTTP file (including `src/app/outbound/auth_ctx/handlers/change_password.py`, completely untouched) completely unaltered (one new line each in `mappings/all.py`, `docker-entrypoint.sh`, `main/ioc/core.py`, `inbound/http/account/router.py`, and the roadmap checklist revert trivially too -- see the File Summary and the note on `GetOwnProfile` below for why the `CoreProvider`/`account/router.py` touches are safe).

---

## Design

### Lessons from the two reference implementations read for this plan

Two existing open-source packages were read in full (not just their docs) to sanity-check this design: `mrtolkien/fastapi_simple_security` (`fastapi_simple_security/security_api_key.py`, `fastapi_simple_security/_sqlite_access.py`) and `florimondmanca/djangorestframework-api-key` (`src/rest_framework_api_key/crypto.py`, `models.py`, `permissions.py`). Three concrete takeaways shaped the design below:

1. **`fastapi_simple_security` stores the raw API key in plaintext** (`api_key TEXT PRIMARY KEY`, a bare `uuid.uuid4()`, checked with a plain `SELECT ... WHERE api_key = ?`) -- no hashing at all. This confirms, by direct contrast, that this plan's "only the hash is ever stored" requirement (already mandated by the roadmap) is a real, deliberate security improvement over a popular reference implementation, not just box-ticking.
2. **`fastapi_simple_security` accepts the key via either a query parameter or a header** (`APIKeyQuery` and `APIKeyHeader`, either one accepted). This plan deliberately accepts the key via **header only** (`X-API-Key`) -- a key in a query string is far more likely to leak into server access logs, proxy logs, and browser history than a header, and there's no reason to trade that away for the marginal convenience of a query-string option.
3. **`djangorestframework-api-key`'s `KeyGenerator`/`AbstractAPIKey` splits a generated key into a non-secret `prefix` and a secret part** (`prefix.secret_key`), storing the prefix in the clear specifically so a UI can show *which* key is which (e.g. in a list) without ever re-displaying or re-deriving the secret. Their `Sha512ApiKeyHasher.salt()` also explicitly returns `""` with the comment "No need for a salt on a high entropy key" -- an independent confirmation of this plan's own reasoning for using an unsalted, deterministic HMAC-SHA256 rather than bcrypt (see below). The prefix idea is worth adopting in miniature: this plan adds a small, non-secret `key_prefix` column purely for display in `ListApiKeys`, without adopting their two-stage "look up by prefix, then verify the secret part" scheme -- that scheme exists in Django's package to avoid a per-row bcrypt-style verify loop, a problem this plan doesn't have, since `ApiKeyHasher` is already a single deterministic hash supporting a direct O(1) `WHERE key_hash = :hash` lookup (see the hashing decision below). Two independent projects converging on "don't salt a high-entropy generated key" is a strong signal this plan's own choice is standard practice, not a shortcut.
4. **`fastapi_simple_security`'s `get_usage_stats()`** (same `_sqlite_access.py` file) returns a raw tuple of per-key usage stats across *all* keys (an admin-only, cross-tenant view, with no CQRS separation -- it's plain SQL glued directly to the FastAPI route). This plan adopts the *idea* -- track how many times a key has authenticated, and when it last did -- but not the shape: `use_count`/`last_used_at` are added as fields on the `ApiKey` aggregate itself, and exposed through a proper query-side vertical (`GetApiKeyUsageStats`, Step 9), scoped to the calling account's own keys only, returning a typed QM rather than a positional tuple. See "Usage analytics" below for why this is a direct counter rather than this project's own domain-event/outbox mechanism.

Separately, the choice of `secrets.token_urlsafe(32)` (see `generate_raw_api_key()` below) plus a fixed, recognizable prefix (`ak_`) is corroborated by a widely-referenced write-up on API-key authentication design: Stephen Touset's "Best-practices based API key authentication" (https://gist.github.com/stouset/f80dd031a57bbfd7dd2ca2636dddc023), which independently arrives at the same two decisions -- a cryptographically secure random source with a documented minimum-entropy floor (128 bits there; `token_urlsafe(32)`'s 256 bits clears it twice over), and a fixed prefix specifically so automated secret-scanners can recognize a leaked key by pattern (formalized there via RFC 8959's `secret-token:` scheme). It also independently confirms hash-based storage over a slow KDF like bcrypt for an already-high-entropy generated secret -- the same conclusion the two repos above already led to.

### The `ApiKey` domain concept: a real entity, not `OutboxMessage`-style infrastructure

The roadmap text says "same shape as the existing `OutboxRepository` port/`SqlaOutboxRepository` adapter pair," but that shape is about the **port/adapter pairing convention**, not about `ApiKey` itself being a thin infrastructure record like `OutboxMessage`. `ApiKey` has real invariants three separate commands need to check consistently (is this key revoked? is it expired? does it belong to the caller?), so it gets a genuine core `Entity`, mirroring `User` (`src/app/core/common/entities/user.py`), not `OutboxMessage`.

`src/app/core/common/entities/api_key.py` (new):
```python
from typing import NewType
from uuid import UUID

from app.core.common.entities.base import Entity
from app.core.common.entities.types_ import UserId
from app.core.common.value_objects.utc_datetime import UtcDatetime

# NewTypes live alongside their entity, exactly like SessionId lives
# alongside AuthSession in src/app/outbound/auth_ctx/model.py.
ApiKeyId = NewType("ApiKeyId", UUID)
ApiKeyHash = NewType("ApiKeyHash", str)  # hex digest -- see the hashing decision below


class ApiKey(Entity[ApiKeyId]):
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
        # Non-secret, stored in the clear -- lets ListApiKeys show e.g.
        # "ak_a1b2c3d4..." so a client can tell keys apart without ever
        # needing the raw key again. Borrowed from
        # djangorestframework-api-key's AbstractAPIKey.prefix; see the
        # "Lessons from the two reference implementations" note above.
        self.key_prefix = key_prefix
        self.label = label
        self._created_at = created_at
        self.expires_at = expires_at
        self.revoked_at = revoked_at
        # Usage-analytics footprint -- see "Usage analytics" note below for
        # why this is a plain counter/timestamp on the same aggregate
        # rather than a domain event.
        self.use_count = use_count
        self.last_used_at = last_used_at

    @property
    def created_at(self) -> UtcDatetime:
        return self._created_at

    # revoked_at/last_used_at are properties over a plain nullable raw
    # `datetime` column each (_revoked_at/_last_used_at), NOT
    # composite(UtcDatetime, ...) like created_at/expires_at -- see the
    # "Nullable UtcDatetime fields" note below Step 3 for why a composite
    # specifically can't be made to work cleanly for a nullable field in
    # this SQLAlchemy version, and why this is the actual fix, not a
    # SQLAlchemy composite() wrapper.
    @property
    def revoked_at(self) -> UtcDatetime | None:
        return UtcDatetime(self._revoked_at) if self._revoked_at is not None else None

    @revoked_at.setter
    def revoked_at(self, value: UtcDatetime | None) -> None:
        self._revoked_at = value.value if value is not None else None

    @property
    def is_revoked(self) -> bool:
        return self._revoked_at is not None

    def is_expired(self, now: UtcDatetime) -> bool:
        return now.value >= self.expires_at.value

    def revoke(self, *, now: UtcDatetime) -> None:
        self.revoked_at = now

    @property
    def last_used_at(self) -> UtcDatetime | None:
        return UtcDatetime(self._last_used_at) if self._last_used_at is not None else None

    @last_used_at.setter
    def last_used_at(self, value: UtcDatetime | None) -> None:
        self._last_used_at = value.value if value is not None else None

    def record_use(self, *, now: UtcDatetime) -> None:
        """Called by ApiKeyIdentityProvider immediately after this key
        successfully authenticates a request. See "Usage analytics" below."""
        self.use_count += 1
        self.last_used_at = now
```

`ApiKey` does **not** raise a domain event on issuance/revocation -- unlike `User.record_event(UserRegisteredEvent(...))` in `create_user()`, there is no roadmap requirement for a side effect (e.g. no "key issued" email), so `PublicApiProvider` needs none of `CoreProvider`'s event-dispatch machinery (`EventDispatcher`, `SendWelcomeEmail`, the handler registry, `EmailSender`). This is the main reason `PublicApiProvider` ends up *leaner* than `CoreProvider`, not just a swap of two bindings.

### Usage analytics: `record_use()`, and why this is a counter, not a domain event

Idea borrowed from `fastapi_simple_security`'s `get_usage_stats()` (`fastapi_simple_security/_sqlite_access.py`), which returns a raw tuple of stats per key -- adopted here as a proper DDD/CQRS vertical, not a raw-tuple admin dump. Confirmed with the user before writing this: usage is recorded as a **plain counter and timestamp on the `ApiKey` aggregate itself** (`use_count`, `last_used_at`, bumped by `record_use()`), committed inline by `ApiKeyIdentityProvider` the moment a key successfully authenticates (see the revised Step 4 below) -- not via this project's own `DomainEvent`/`EventHandler`/`HybridEventDispatcher` outbox machinery (the same mechanism `CreateUser` uses for `UserRegisteredEvent` → `SendWelcomeEmail`).

This is a deliberate boundary call, not an oversight: that outbox machinery exists for side effects that cross an aggregate/bounded-context boundary and need reliable, possibly-async delivery to an unrelated consumer (an email send, in the existing example). Usage-tracking never leaves `ApiKey`'s own consistency boundary -- it's the same aggregate updating its own stats -- so raising an event, staging it, and dispatching it to a background handler just to increment a field on the row that raised it would be the wrong-sized tool: an extra table (outbox), an extra class (the event), an extra handler, and a Celery round-trip, all to do what one `UPDATE` already does. The domain-event path stays the right one to reach for the moment usage data needs to flow *out* of this aggregate (e.g. to a separate analytics/reporting service) -- not for this.

One consequence worth documenting rather than treating as a bug: because `ApiKeyIdentityProvider` records a use on **every** successful authentication, a caller checking their own key's usage via `GetApiKeyUsageStats` (Step 9 below) necessarily bumps that same key's `use_count` by one in the process of checking it -- the same "the page-view counter increments when you view the page" behavior a naive reading might mistake for a race condition. `test_get_api_key_usage_stats.py`'s integration test asserts this directly rather than around it.

`ApiKeyExpiryDays` (`src/app/core/common/value_objects/api_key_expiry_days.py`, new) is a proper `ValueObject` (like `RawPassword`), enforcing the caller-chosen expiry's bounds:
```python
from dataclasses import dataclass
from typing import ClassVar

from app.core.common.exceptions import BusinessTypeError
from app.core.common.value_objects.base import ValueObject


@dataclass(frozen=True, slots=True, repr=False)
class ApiKeyExpiryDays(ValueObject):
    MIN_DAYS: ClassVar[int] = 1
    MAX_DAYS: ClassVar[int] = 365

    value: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (self.MIN_DAYS <= self.value <= self.MAX_DAYS):
            raise BusinessTypeError(f"Expiry must be between {self.MIN_DAYS} and {self.MAX_DAYS} days.")
```

Two small, pure factories, each in its own new file -- mirroring `src/app/outbound/auth_ctx/id_factory.py::create_session_id()` being its own dedicated file rather than folded into the shared `src/app/core/common/factories/id_factory.py` (which is left completely untouched):
- `src/app/core/common/factories/api_key_id_factory.py::create_api_key_id() -> ApiKeyId` (uuid7, same scheme as `create_user_id()`).
- `src/app/core/common/factories/raw_api_key_factory.py::generate_raw_api_key() -> str` (`f"ak_{secrets.token_urlsafe(32)}"` -- 256 bits of entropy; the `ak_` prefix mirrors GitHub's/Stripe's own prefixing convention, letting automated secret-scanners recognize a leaked key by pattern).

### The port/adapter pair, and the CQRS split it has to respect

`pyproject.toml`'s `import-linter` contracts forbid `core.commands` ↔ `core.queries` cross-imports. `ListApiKeys` is a query; `IssueApiKey`/`RevokeApiKey` are commands. So, mirroring `UserTxStorage`/`UserReader`'s existing split for `User`, `ApiKey` gets **two** ports:

- `src/app/core/commands/ports/api_key_repository.py` -- `ApiKeyRepository` Protocol:
  ```python
  class ApiKeyRepository(Protocol):
      def add(self, api_key: ApiKey) -> None: ...
      async def get_by_id(self, api_key_id: ApiKeyId, *, for_update: bool = False) -> ApiKey | None: ...
      async def get_by_key_hash(self, key_hash: ApiKeyHash) -> ApiKey | None: ...
      async def revoke_all_for_user(self, user_id: UserId) -> None: ...
  ```
  `get_by_key_hash` lives on this Protocol because it *is* core business-logic meaning: the outbound `ApiKeyIdentityProvider` depends on this exact port to authenticate a request. That's a legal dependency direction -- `outbound` may depend on `core` ports freely -- and mirrors `AuthSessionIdentityProvider` depending on `AuthService`.

- `src/app/core/queries/ports/api_key_reader.py` -- `ApiKeyReader` Protocol + `ApiKeyQm`/`ListApiKeysQm` `TypedDict`s, mirroring `UserReader`/`ListUsersQm` exactly:
  ```python
  class ApiKeyQm(TypedDict):
      id: UUID
      key_prefix: str          # e.g. "ak_a1b2c3d4" -- enough to tell keys apart, never the secret
      label: str | None
      created_at: datetime
      expires_at: datetime
      revoked_at: datetime | None

  class ListApiKeysQm(TypedDict):
      api_keys: list[ApiKeyQm]
      total: int
      limit: int
      offset: int

  class ApiKeyUsageStatsQm(TypedDict):
      id: UUID
      user_id: UUID          # not returned to the caller (stripped by the response schema) --
                              # present only so GetApiKeyUsageStats can check ownership itself,
                              # mirroring how RevokeApiKey checks ownership after an unscoped load
      key_prefix: str
      label: str | None
      use_count: int
      last_used_at: datetime | None
      created_at: datetime
      expires_at: datetime
      revoked_at: datetime | None

  class ApiKeyReader(Protocol):
      async def list_by_user(
          self, user_id: UserId, *, pagination: OffsetPaginationParams, sorting: SortingParams
      ) -> ListApiKeysQm: ...

      async def get_usage_stats_by_id(self, api_key_id: ApiKeyId) -> ApiKeyUsageStatsQm | None:
          """Deliberately unscoped by user_id (unlike list_by_user) -- mirrors
          ApiKeyRepository.get_by_id()'s shape, so GetApiKeyUsageStats can raise the
          same 404-vs-403 distinction RevokeApiKey already establishes for by-id
          access to someone else's key, rather than folding both cases into one 404."""
          ...
  ```
  `ApiKeyQm` never includes `key_hash` -- same "never expose infrastructure secrets" principle `UserQm` already follows by never exposing `password_hash`. `ApiKeyUsageStatsQm` follows the same rule and additionally never exposes `key_hash`.

Adapters, both using the **primary** `AsyncSession` (the same one `SqlaUserTxStorage`/`SqlaOutboxRepository` use) -- `ApiKey` is core-domain data living in the main schema, not the separate `auth_ctx` bounded context's own session:
- `src/app/outbound/adapters/sqla_api_key_repository.py::SqlaApiKeyRepository` -- `add()` via `session.add()`; `get_by_id()`/`get_by_key_hash()` via `session.get()`/`select(...)`; `revoke_all_for_user()` via a bulk `UPDATE` (not a load-then-mutate loop), mirroring `SqlaOutboxRepository`'s direct-SQL style.
- `src/app/outbound/adapters/sqla_api_key_reader.py::SqlaApiKeyReader` -- `list_by_user()`, structurally identical to `SqlaUserReader.list_users()`; `get_usage_stats_by_id()`, a single unscoped `select(...)` by primary key, returning `None` for an unknown id.

### The key-hashing decision: HMAC-SHA256, not bcrypt

`BcryptPasswordHasher` is deliberately slow (tunable work factor) and per-instance-salted -- both correct for a **human-chosen, comparatively low-entropy** password, where the threat is offline brute-force guessing. A generated API key is the opposite kind of secret: `generate_raw_api_key()` produces 256 bits of `secrets`-sourced entropy, far beyond anything a slow KDF meaningfully protects against. Reusing bcrypt for API keys would be actively harmful for two reasons:

1. **Cost with no security benefit** -- every API-authenticated request would pay bcrypt's deliberately-expensive per-call latency for a secret that doesn't need it, directly undermining the "customers integrate programmatically" use case.
2. **Structurally incompatible with the required lookup** -- bcrypt salts each hash independently, so there's no way to look up "the row whose bcrypt hash matches this candidate" except iterating every live key -- O(n) bcrypt calls per request. A deterministic hash supports `SELECT ... WHERE key_hash = :hash`, an O(1) indexed lookup, exactly like session lookup by id today.

So: a new, dedicated, **synchronous** port (no thread pool/semaphore needed -- HMAC-SHA256 is microseconds):

`src/app/core/common/ports/api_key_hasher.py`:
```python
class ApiKeyHasher(Protocol):
    def hash(self, raw_key: str) -> ApiKeyHash: ...
```
(No `verify()` -- HMAC-SHA256 is deterministic, so "verify" is just "hash the candidate and look it up.")

`src/app/outbound/adapters/hmac_sha256_api_key_hasher.py::HmacSha256ApiKeyHasher` derives a domain-separated sub-key from the **existing** `PasswordHasherSettings.PEPPER` (via `hmac.new(key=pepper, msg=b"api-key-v1", digestmod=hashlib.sha256).digest()`, standard key-separation hygiene rather than reusing the password pepper directly), then `hmac.new(key=that_subkey, msg=raw_key.encode(), digestmod=hashlib.sha256).hexdigest()`. **This feature needs zero new settings, env vars, or `pyproject.toml` dependencies** -- `hashlib`/`hmac`/`secrets` are stdlib, already implicitly used by `bcrypt_password_hasher.py`.

### `ApiKeyIdentityProvider` and `ApiKeyAccessRevoker`

`src/app/outbound/adapters/api_key_identity_provider.py` (new) implements the existing, unmodified `IdentityProvider` port, mirroring `AuthSessionIdentityProvider`'s shape but with a much shorter dependency chain -- no `CookieManager`/`AuthService`/`JwtProcessor`:
```python
API_KEY_HEADER_NAME: Final[str] = "X-API-Key"


class ApiKeyAuthenticationError(BaseError):
    default_message: ClassVar[str] = "Invalid or expired API key."


class ApiKeyIdentityProvider(IdentityProvider):
    def __init__(
        self,
        request: Request,
        api_key_repository: ApiKeyRepository,
        api_key_hasher: ApiKeyHasher,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
    ) -> None: ...

    async def get_current_user_id(self) -> UserId:
        raw_key = self._request.headers.get(API_KEY_HEADER_NAME)
        if not raw_key:
            raise ApiKeyAuthenticationError
        key_hash = self._api_key_hasher.hash(raw_key)
        api_key = await self._api_key_repository.get_by_key_hash(key_hash)
        if api_key is None or api_key.is_revoked or api_key.is_expired(self._utc_timer.now):
            raise ApiKeyAuthenticationError

        # Usage-analytics footprint (see "Usage analytics" note above): a
        # plain counter/timestamp bump on the same row that just
        # authenticated, committed inline -- deliberately not a domain
        # event, since nothing outside ApiKey's own boundary needs to know.
        api_key.record_use(now=self._utc_timer.now)
        await self._transaction_manager.commit()
        return api_key.user_id
```
`ApiKeyAuthenticationError` is defined right in this file, exactly like `CliIdentityError` is defined directly inside `src/app/main/cli/identity_provider.py` -- keeps the whole mechanism in one small, self-contained, deletable file.

`TransactionManager` is a new dependency for this adapter (Step 3's original sketch had none, since it was purely a read before this addition) -- every authenticated request now commits one small `UPDATE` as a side effect of resolving identity, in exchange for `use_count`/`last_used_at` being correct and current for `GetApiKeyUsageStats` (Step 9). This cost was weighed explicitly against a domain-event/outbox alternative and accepted as the right-sized tradeoff for a same-aggregate counter -- see "Usage analytics" above.

`AccessRevoker.remove_all_user_access()` is what `CurrentUserService` calls when the resolved user turns out to be missing/inactive, and what a password change now also calls (see below). Today's `AuthSessionAccessRevoker` only revokes **sessions**; by the same symmetry, the new `ApiKeyAccessRevoker` (`src/app/outbound/adapters/api_key_access_revoker.py`) only revokes **API keys**:
```python
class ApiKeyAccessRevoker(AccessRevoker):
    def __init__(self, api_key_repository: ApiKeyRepository, transaction_manager: TransactionManager) -> None: ...

    async def remove_all_user_access(self, user_id: UserId) -> None:
        await self._api_key_repository.revoke_all_for_user(user_id)
        await self._transaction_manager.commit()
```

### Mapping which "account use cases" this feature mirrors

| Existing account use case | API-key equivalent | Included? |
|---|---|---|
| `SignUp` (open self-registration) | -- | **No** -- explicitly excluded by the roadmap. An API key/password change can only ever apply to an *already-existing* account. |
| `LogIn` (verify credentials, issue a session) | `IssueApiKey` (verify credentials, issue a key) | **Yes** -- the login-equivalent. |
| `LogOut` (end current session) | -- | **No equivalent needed.** "Ending" one key's usability *is* `RevokeApiKey`; there's no separate "current session" concept for a stateless header credential. |
| `ChangePassword` (self-service password management) | -- | **No -- considered, then removed.** An API key should only ever authorize what an API key is for (mint/list/revoke keys); it shouldn't also be able to change the account's login password -- only `IssueApiKey` needs a password at all. Also would have meant touching the private app's already-working `ChangePassword`. See Step 10. |
| Admin user-management commands (`CreateUser`, `SetUserPassword`, `GrantAdmin`, ...) | -- | **No** -- out of scope; this plan does not add an admin "manage any user's keys" capability, which would be new business-domain scope the roadmap explicitly warns against inventing. |

Three commands + two queries (`ListApiKeys` and the new `GetApiKeyUsageStats`, Step 9), precisely:

**`IssueApiKey`** (`src/app/core/commands/issue_api_key.py`, a **command**) -- mirrors `LogIn`'s verify-credentials shape, reusing the **existing, unmodified** `UserFinder`/`SqlaUserFinder` port+adapter pair the CLI plan already added (`src/app/core/common/ports/user_finder.py` / `src/app/outbound/adapters/sqla_user_finder.py`) -- a second, unrelated feature reusing that port as-is is a good sign it was genuinely general-purpose, not CLI-specific. **Deliberate scope trim vs. `LogIn`**: `LogIn` accepts either email or username; `IssueApiKeyRequest` accepts **username only**, so it can reuse `UserFinder` verbatim rather than extending it. **Deliberate difference from `LogIn`**: `IssueApiKey` does not check "already authenticated" -- minting an additional key while another key/session is already valid is the normal case (exactly how GitHub/Stripe let you mint additional PATs from an already-logged-in dashboard), not a corner case to block.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class IssueApiKeyRequest:
    username: str
    password: str
    expires_in_days: int
    label: str | None = None

class IssueApiKeyResponse(TypedDict):
    id: UUID
    raw_key: str          # shown exactly once -- never persisted, never returned again
    label: str | None
    created_at: datetime
    expires_at: datetime

class IssueApiKey:
    def __init__(
        self,
        user_finder: UserFinder,
        user_service: UserService,
        utc_timer: UtcTimer,
        api_key_hasher: ApiKeyHasher,
        api_key_repository: ApiKeyRepository,
        transaction_manager: TransactionManager,
    ) -> None: ...

    async def execute(self, request: IssueApiKeyRequest) -> IssueApiKeyResponse:
        user = await self._user_finder.find_by_username(Username(request.username))
        if user is None or not await self._user_service.is_password_valid(user, RawPassword(request.password)):
            raise InvalidApiKeyCredentialsError
        if not user.is_active:
            raise InvalidApiKeyCredentialsError(API_KEY_ACCOUNT_INACTIVE)

        expiry_days = ApiKeyExpiryDays(request.expires_in_days)
        now = self._utc_timer.now
        expires_at = UtcDatetime(now.value + timedelta(days=expiry_days.value))
        raw_key = generate_raw_api_key()
        api_key = ApiKey(
            id_=create_api_key_id(), user_id=user.id_, key_hash=self._api_key_hasher.hash(raw_key),
            key_prefix=raw_key[:11],  # "ak_" + 8 chars -- non-secret, display-only
            label=request.label, created_at=now, expires_at=expires_at,
        )
        self._api_key_repository.add(api_key)
        await self._transaction_manager.commit()
        return IssueApiKeyResponse(
            id=api_key.id_, raw_key=raw_key, label=api_key.label,
            created_at=now.value, expires_at=expires_at.value,
        )
```
`InvalidApiKeyCredentialsError`/`API_KEY_ACCOUNT_INACTIVE` live in a **new** file, `src/app/core/commands/api_key_exceptions.py` -- not added to the existing `src/app/core/commands/exceptions.py`.

**`ListApiKeys`** (`src/app/core/queries/list_api_keys.py`, a **query**) -- same authorization shape as `ChangePassword`: authenticated (via whichever `IdentityProvider` the container has -- here, `ApiKeyIdentityProvider`), no `authorize()` permission check, scoped to `current_user.id_` only.

**`GetApiKeyUsageStats`** (`src/app/core/queries/get_api_key_usage_stats.py`, a **query**, new) -- the analytics vertical (see "Usage analytics" above for the design rationale). Unlike `ListApiKeys`, this is a by-id lookup, so it follows `RevokeApiKey`'s ownership-check convention rather than `ListApiKeys`'s "scope the query itself" one:

```python
class ApiKeyNotFoundError(BaseError): ...  # defined here, not reused from core.commands --
                                            # core.queries may never import core.commands

class GetApiKeyUsageStats:
    def __init__(self, current_user_service: CurrentUserService, api_key_reader: ApiKeyReader) -> None:
        self._current_user_service = current_user_service
        self._api_key_reader = api_key_reader

    async def execute(self, api_key_id: ApiKeyId) -> ApiKeyUsageStatsQm:
        current_user = await self._current_user_service.get_current_user()
        stats = await self._api_key_reader.get_usage_stats_by_id(api_key_id)
        if stats is None:
            raise ApiKeyNotFoundError
        if stats["user_id"] != current_user.id_:
            raise AuthorizationError
        return stats
```
`AuthorizationError` is the same existing, shared `core.common.authorization.exceptions.AuthorizationError` `RevokeApiKey` already reuses unmodified -- legal for a query to import, since it lives in `core.common`, not `core.commands`. The HTTP layer's response schema for this endpoint omits `user_id` from what's actually serialized back to the caller -- it exists on `ApiKeyUsageStatsQm` only so this check has something to compare against.

**`RevokeApiKey`** (`src/app/core/commands/revoke_api_key.py`, a **command**) -- loads the key by id, raises `ApiKeyNotFoundError` (404) if missing, raises the existing `AuthorizationError` (reused unmodified -- no new Permission needed for a plain ownership check) if `api_key.user_id != current_user.id_`, and is **idempotent**: revoking an already-revoked key is a silent no-op.

**No `ChangeOwnPassword`.** See Step 10 and the "Mapping" table above -- removed from scope. `src/app/outbound/auth_ctx/handlers/change_password.py` remains the only password-change surface in this codebase, untouched.

### Symmetric profile access: proof that cookie and API-key auth do "the same things"

Confirmed with the user: an account should be able to do the same self-service things whether it's authenticated via browser cookie (the future frontend) or via API key (a B2B backend), because a future frontend and a machine client are both just callers behind the same `IdentityProvider` port. The concrete acceptance test the user gave: **can the same account retrieve its own profile both via cookie session and via API key?**

This is where the whole design's payoff shows up concretely: `CoreProvider` (private/cookie app) and `PublicApiProvider` (public/API-key app) both bind `IdentityProvider` to a different concrete adapter (`AuthSessionIdentityProvider` vs. `ApiKeyIdentityProvider`), but `CurrentUserService` -- and anything built on top of it -- has no idea which one it's talking to. So a single new query, `GetOwnProfile` (`src/app/core/queries/get_own_profile.py`), depends on nothing but `CurrentUserService` and returns the existing `UserQm` (`src/app/core/queries/models/user.py`, already used by `ListUsers` -- no new DTO needed), and gets bound, unmodified, into **both** containers -- exposed as `GET /api/v1/account/profile/` on the private app and `GET /public/v1/account/profile/` on the public app. Same class, same logic, two transports.

```python
class GetOwnProfile:
    def __init__(self, current_user_service: CurrentUserService) -> None:
        self._current_user_service = current_user_service

    async def execute(self) -> UserQm:
        current_user = await self._current_user_service.get_current_user()
        return UserQm(
            id=current_user.id_, username=current_user.username, email=current_user.email,
            phone_number=current_user.phone_number, role=current_user.role,
            is_active=current_user.is_active, created_at=current_user.created_at,
            updated_at=current_user.updated_at,
        )
```
No `authorize()` call -- viewing your own profile needs nothing beyond being an authenticated, active user, the same no-RBAC shape `ChangePassword` already uses for self-service actions.

**A deliberate, narrow exception to "never touch existing providers," and why it's safe:** wiring `GetOwnProfile` into the private app means adding one line -- `get_own_profile = provide(GetOwnProfile)` -- to the existing `CoreProvider` (`src/app/main/ioc/core.py`), plus one new sub-router registration line in the existing `src/app/inbound/http/account/router.py::make_account_router()`. This is categorically different from the CLI/worker situation this plan otherwise follows so carefully: `WorkerProvider`/`CliProvider` exist because `CoreProvider` could not be reused *as a whole* for a different **process** (no `Request` available). Here, the private app is the same process/container `CoreProvider` already serves -- adding one new business-query binding to it is the exact same kind of change every one of `CoreProvider`'s existing ~11 bindings already represents (that's how `CreateUser`, `GrantAdmin`, etc. all got there in the first place), not a restructuring of it. `PublicApiProvider` still gets its own, independent `get_own_profile = provide(GetOwnProfile)` binding -- `CoreProvider` and `PublicApiProvider` remain two fully separate providers, neither parameterized or split to accommodate the other. The feature-delete test still holds cleanly: reverting the one new line in each of `CoreProvider`/`account/router.py` and deleting `core/queries/get_own_profile.py` plus the two new route files leaves every pre-existing binding and behavior completely unaffected.

### The public router group and its own always-on docs page

FastAPI's mounted-sub-application mechanism (`app.mount(path, sub_app)`) is what the roadmap means by "more than one OpenAPI docs UI via mounted sub-apps/routers" -- each mounted `FastAPI` instance is a fully independent ASGI app with its own `docs_url`/`redoc_url`/`openapi.json`, its own middleware, and its own Dishka container. `src/app/main/run_public_api.py` (new) adds two composition functions, leaving `src/app/main/run.py::make_app()` **completely unmodified**:

```python
def make_public_api_app(
    *di_providers: Provider,
    password_hasher_settings: PasswordHasherSettings | None = None,
    postgres_settings: PostgresSettings | None = None,
    sqla_settings: SqlaSettings | None = None,
) -> FastAPI:
    if password_hasher_settings is None:
        password_hasher_settings = load_password_hasher_settings()
    if postgres_settings is None:
        postgres_settings = load_postgres_settings()
    if sqla_settings is None:
        sqla_settings = load_sqla_settings()

    app = FastAPI(
        title="Public API",
        summary="API-key-authenticated surface for programmatic integrations.",
        # Always reachable, unlike the private app's ENVIRONMENT-gated
        # /docs (see make_app() in run.py) -- the point of this feature is
        # that a customer integrating against this API can read its docs
        # regardless of this deployment's ENVIRONMENT.
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=make_lifespan(),  # reused, unmodified, from main/run.py
    )
    container = make_async_container(
        *get_public_api_providers(), *di_providers,
        context={
            PasswordHasherSettings: password_hasher_settings,
            PostgresSettings: postgres_settings,
            SqlaSettings: sqla_settings,
        },
    )
    setup_dishka(container, app)
    app.include_router(make_public_router())
    return app


def make_app_with_public_api(*di_providers: Provider, **make_app_kwargs: Any) -> FastAPI:
    """The real process entrypoint (see docker-entrypoint.sh) -- composes the
    existing, unmodified make_app() with the new public sub-app, by
    addition only, never by editing it."""
    app = make_app(*di_providers, **make_app_kwargs)
    public_app = make_public_api_app()
    app.mount("/public", public_app)

    # Starlette's Mount does not forward the ASGI `lifespan` protocol to a
    # mounted sub-application -- it only routes http/websocket scopes by
    # path -- so public_app's own lifespan (and its container's
    # startup/shutdown) would silently never run if left as-is. Compose
    # both lifespans explicitly instead of editing anything in run.py.
    main_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with main_lifespan(app), public_app.router.lifespan_context(public_app):
            yield

    app.router.lifespan_context = combined_lifespan
    return app
```

This mounted-sub-app lifespan-forwarding gap is a known Starlette/FastAPI limitation, not a guess -- but it's exactly the kind of thing to *prove*, not just assert, so Step 6 below is a dedicated, real-Postgres integration test that exercises `make_app_with_public_api()` end-to-end and would fail loudly if this composition were wrong.

`src/app/inbound/http/public_api/router.py::make_public_router()` mounts `/v1/api-keys/...` (via `public_api/api_keys/router.py::make_api_keys_router()`) and, from Step 11 onward, `/v1/account/...` (via `public_api/account/router.py::make_account_router()`, for `GetOwnProfile` only -- there is no public-API password-change route, see the "Mapping which account use cases" table above) -- versioned, mirroring the private API's own `/api/v1` discipline. The list/revoke-keys routes carry `dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME))]` at the router level -- mirroring `Depends(APIKeyCookie(...))` on existing routers -- purely for OpenAPI display; real enforcement happens inside `ApiKeyIdentityProvider`/`CurrentUserService`, per this repo's existing convention. The issue-key route (`POST /v1/api-keys/`) carries no such dependency -- it's the "open, prove who you are via the request body" route, exactly like `POST /account/login/`.

Final public paths: `POST /public/v1/api-keys/`, `GET /public/v1/api-keys/`, `DELETE /public/v1/api-keys/{api_key_id}/`, `GET /public/v1/api-keys/{api_key_id}/usage/`, `GET /public/v1/account/profile/` (Step 11), plus always-on `GET /public/docs`, `GET /public/redoc`, `GET /public/openapi.json`.

### A known, accepted tradeoff: two connection pools in one process

`PersistenceSqlaProvider.provide_async_engine` is `Scope.APP`, so `get_public_api_providers()` reusing it means the public sub-app's container opens its **own**, independent `AsyncEngine`/connection pool against the same Postgres, alongside the main app's own pool -- both inside the same process. This is a real, deliberate resource cost (roughly doubling this process's steady-state connection count), confirmed acceptable at this deployment's scale (~300 clients/day) as part of choosing the mounted-sub-app model over a separate service. Sharing one `AsyncEngine`/`async_sessionmaker` across both containers is a legitimate future optimization, explicitly deferred.

---

## Package layout

All new. Nothing existing is modified except the explicitly-listed additive touches at the bottom.

```
src/app/core/common/entities/api_key.py                      # ApiKey entity, ApiKeyId/ApiKeyHash NewTypes
src/app/core/common/value_objects/api_key_expiry_days.py      # ApiKeyExpiryDays VO
src/app/core/common/ports/api_key_hasher.py                   # ApiKeyHasher Protocol
src/app/core/common/factories/api_key_id_factory.py            # create_api_key_id()
src/app/core/common/factories/raw_api_key_factory.py            # generate_raw_api_key()

src/app/core/commands/ports/api_key_repository.py               # ApiKeyRepository Protocol
src/app/core/commands/api_key_exceptions.py                     # InvalidApiKeyCredentialsError, ApiKeyNotFoundError
src/app/core/commands/issue_api_key.py                          # IssueApiKey, IssueApiKeyRequest/Response
src/app/core/commands/revoke_api_key.py                          # RevokeApiKey, RevokeApiKeyRequest

src/app/core/queries/ports/api_key_reader.py                     # ApiKeyReader, ApiKeyQm, ListApiKeysQm, ApiKeyUsageStatsQm
src/app/core/queries/list_api_keys.py                            # ListApiKeys, ListApiKeysRequest, ApiKeySortingField
src/app/core/queries/get_api_key_usage_stats.py                  # GetApiKeyUsageStats, ApiKeyNotFoundError -- the analytics vertical
src/app/core/queries/get_own_profile.py                          # GetOwnProfile -- shared by both the cookie and API-key apps

src/app/outbound/adapters/hmac_sha256_api_key_hasher.py          # HmacSha256ApiKeyHasher
src/app/outbound/adapters/sqla_api_key_repository.py             # SqlaApiKeyRepository
src/app/outbound/adapters/sqla_api_key_reader.py                 # SqlaApiKeyReader
src/app/outbound/adapters/api_key_identity_provider.py           # ApiKeyIdentityProvider, ApiKeyAuthenticationError, API_KEY_HEADER_NAME
src/app/outbound/adapters/api_key_access_revoker.py              # ApiKeyAccessRevoker

src/app/outbound/persistence_sqla/mappings/api_key.py            # api_keys_table, map_api_keys_table() -- columns: id (PK), user_id (FK users.id), key_hash (unique, indexed), key_prefix, label, created_at, expires_at, revoked_at
src/app/outbound/persistence_sqla/alembic/versions/<ts>_api_keys.py  # new migration, down_revision = 6376b41ed669 (current head)

src/app/main/ioc/public_api.py                                      # PublicApiProvider, get_public_api_providers()
src/app/main/run_public_api.py                                   # make_public_api_app(), make_app_with_public_api()

src/app/inbound/http/public_api/__init__.py
src/app/inbound/http/public_api/router.py                        # make_public_router()
src/app/inbound/http/public_api/api_keys/__init__.py
src/app/inbound/http/public_api/api_keys/router.py               # make_api_keys_router()
src/app/inbound/http/public_api/api_keys/issue_api_key.py
src/app/inbound/http/public_api/api_keys/list_api_keys.py
src/app/inbound/http/public_api/api_keys/revoke_api_key.py
src/app/inbound/http/public_api/api_keys/get_api_key_usage_stats.py   # GET /v1/api-keys/{api_key_id}/usage/
src/app/inbound/http/public_api/account/__init__.py
src/app/inbound/http/public_api/account/router.py                # make_account_router() -- GetOwnProfile only, no password-change route
src/app/inbound/http/public_api/account/profile.py               # GET /public/v1/account/profile/
src/app/inbound/http/account/profile.py                          # GET /api/v1/account/profile/ -- new leaf on the EXISTING private account router

tests/unit/core/common/entities/test_api_key.py
tests/unit/core/common/value_objects/test_api_key_expiry_days.py
tests/unit/outbound/adapters/test_hmac_sha256_api_key_hasher.py
tests/unit/outbound/adapters/test_api_key_identity_provider.py
tests/unit/outbound/adapters/test_api_key_access_revoker.py
tests/unit/core/commands/api_keys/__init__.py
tests/unit/core/commands/api_keys/factories.py                  # fakes: FakeApiKeyRepository, FakeApiKeyReader, FakeApiKeyHasher
tests/unit/core/commands/api_keys/test_issue_api_key.py
tests/unit/core/commands/api_keys/test_revoke_api_key.py
tests/unit/core/queries/test_list_api_keys.py
tests/unit/core/queries/test_get_api_key_usage_stats.py
tests/unit/core/queries/test_get_own_profile.py

tests/integration/with_infra/api_keys/__init__.py
tests/integration/with_infra/api_keys/conftest.py                # it_public_app, it_public_client
tests/integration/with_infra/api_keys/test_sqla_api_key_repository.py
tests/integration/with_infra/api_keys/test_sqla_api_key_reader.py
tests/integration/with_infra/api_keys/test_provider_container.py
tests/integration/with_infra/api_keys/test_public_docs_availability.py
tests/integration/with_infra/api_keys/test_issue_api_key.py
tests/integration/with_infra/api_keys/test_list_api_keys.py
tests/integration/with_infra/api_keys/test_revoke_api_key.py
tests/integration/with_infra/api_keys/test_get_api_key_usage_stats.py
tests/integration/with_infra/api_keys/test_inactive_user_revokes_keys.py
tests/integration/with_infra/api_keys/test_get_profile.py         # public /account/profile/
tests/integration/with_infra/account/test_get_profile.py          # private /account/profile/ (new test file in an existing test directory)
```

Explicit additive touches to existing files (all one line or a small, obviously-reversible block):
- `src/app/outbound/persistence_sqla/mappings/all.py` -- one new import + one new call in `map_tables()`, registering `map_api_keys_table()`.
- `src/app/main/ioc/core.py` -- one new `get_own_profile = provide(GetOwnProfile)` line on the existing `CoreProvider` (see the `GetOwnProfile` design note above for why this specific addition, unlike a process-level split, is safe and consistent with how every other binding got there).
- `src/app/inbound/http/account/router.py` -- one new sub-router registration line, wiring in `profile.py`'s `GET /profile/`, the same way every existing sub-router (`sign_up`, `log_in`, `log_out`, `change_password`) is already registered there.
- `docker-entrypoint.sh` -- the `start)` case's `uvicorn app.main.run:make_app --factory ...` (line 12) becomes `uvicorn app.main.run_public_api:make_app_with_public_api --factory ...`. This is the one unavoidable touch that makes the feature reachable at all (mirrors the CLI plan's own honest acknowledgment of its unavoidable `Makefile` touch) -- `main/run.py` itself is never edited.
- `docs/plans/0-production-readiness-roadmap.md` -- flip line 51's `- [ ]` to `- [x]`.
- `README.md`'s TODO checklist -- sync the matching line, per this project's standing convention that the two checklists mirror each other.
- No `pyproject.toml` change -- no new dependency (stdlib `hashlib`/`hmac`/`secrets` only, plus the already-present `bcrypt`, reused only for password verification at issuance/change, exactly as it already is).

---

## Proposed Changes

Test file(s) before production file(s) per step (RED → GREEN → refactor), per this project's TDD convention. Both application and test code should carry liberal explanatory comments per this project's standing preference, especially for the non-obvious design calls flagged above (why HMAC-SHA256 not bcrypt, why the lifespan has to be composed manually, why revoking API keys on password change is intentional).

**Step 1 -- `ApiKey` entity + `ApiKeyExpiryDays` value object + id/raw-key factories.**
- Test: `tests/unit/core/common/entities/test_api_key.py` -- `is_revoked` false/true before/after `revoke()`; `is_expired(now)` true/false around the boundary; `revoke()` sets `revoked_at`; a new key starts with `use_count == 0` and `last_used_at is None`; `record_use(now=...)` increments `use_count` by exactly 1 and sets `last_used_at`; calling it twice with two different `now` values leaves `use_count == 2` and `last_used_at` equal to the *second* call's `now`.
- Test: `tests/unit/core/common/value_objects/test_api_key_expiry_days.py` -- valid range accepted, `< MIN_DAYS`/`> MAX_DAYS` raise `BusinessTypeError`.
- Production: `core/common/entities/api_key.py`, `core/common/value_objects/api_key_expiry_days.py`, `core/common/factories/api_key_id_factory.py`, `core/common/factories/raw_api_key_factory.py`.

**Step 2 -- `ApiKeyHasher` port + `HmacSha256ApiKeyHasher` adapter.**
- Test: `tests/unit/outbound/adapters/test_hmac_sha256_api_key_hasher.py` -- same raw key + same pepper hashes identically (deterministic, supports lookup-by-hash); different raw keys hash differently; different peppers produce different hashes for the same raw key (proves the pepper is actually used).
- Production: `core/common/ports/api_key_hasher.py`, `outbound/adapters/hmac_sha256_api_key_hasher.py`.

**Step 3 -- `ApiKeyRepository`/`ApiKeyReader` ports + `Sqla*` adapters + mapping + migration.**
- Test: `tests/integration/with_infra/api_keys/test_sqla_api_key_repository.py` -- constructs `SqlaApiKeyRepository(it_session)` directly (no DI container yet): `add()` then `get_by_id()` round-trips; `get_by_key_hash()` finds the right row and returns `None` for an unknown hash; `revoke_all_for_user()` sets `revoked_at` on every un-revoked key for that user and leaves another user's keys untouched. This test's mere ability to run at all also proves the migration/mapping are correct (`tests/integration/migrations/test_stairway.py` already generically covers up/down correctness).
- Test: `tests/integration/with_infra/api_keys/test_sqla_api_key_reader.py` -- `list_by_user()` pagination/sorting/total, scoped correctly to one user only; `get_usage_stats_by_id()` returns the right `ApiKeyUsageStatsQm` (including `use_count`/`last_used_at`) for a known id, and `None` for an unknown one, regardless of which user owns it (ownership is checked by the query, not the reader -- see Step 9).
- Production: `core/commands/ports/api_key_repository.py`, `core/queries/ports/api_key_reader.py`, `outbound/adapters/sqla_api_key_repository.py`, `outbound/adapters/sqla_api_key_reader.py`, `outbound/persistence_sqla/mappings/api_key.py` (+ its one-line registration in `mappings/all.py`), the new Alembic migration (`down_revision` pointing at the current head, `6376b41ed669`).

**Nullable `UtcDatetime` fields -- a real bug hit and fixed during this step, worth reading before mapping any future nullable value-object column.** `revoked_at`/`last_used_at` are the first `UtcDatetime | None` fields this codebase has ever persisted (`created_at`/`expires_at` are never `None`). The first attempt mapped them with `composite(UtcDatetime, ...)`, same as the non-nullable fields -- this crashes on load, because `composite()`'s read path calls `UtcDatetime(raw_value)` unconditionally, even when `raw_value` is `NULL`, and `UtcDatetime`'s constructor correctly rejects `None`. The next attempt swapped in a small `None`-tolerant wrapper *function* as the composite's `class_` -- this fixes reading, but breaks writing instead: SQLAlchemy generates a composite's column-extraction logic by introspecting `class_` as a dataclass, which a plain wrapper function isn't, so assigning an actual `UtcDatetime` value back to the attribute then fails with `Composite class ... is not a dataclass and does not define a __composite_values__() method`. **The actual fix: don't use `composite()` for these two fields at all.** `ApiKey.revoked_at`/`last_used_at` are plain Python `@property`/setter pairs over private `_revoked_at`/`_last_used_at` attributes, which map directly to plain nullable `DateTime` columns (no `composite()` wrapper anywhere) -- the `None`-check and the `UtcDatetime` wrap/unwrap happen entirely in ordinary Python code in the entity itself, sidestepping SQLAlchemy's composite null-handling instead of fighting it. `created_at`/`expires_at` are untouched and keep using `composite(UtcDatetime, ...)` directly, since they're never nullable and were never part of this bug. `docs/plans/9-organizations.md`'s `OrganizationMembership.accepted_at` (also a nullable `UtcDatetime`) should follow this same plain-property pattern, not either of the two broken composite attempts above.

**A second, unrelated real problem hit in this same step, worth reading before writing any future bulk `UPDATE`/`DELETE` against a mapped entity's table on an `AsyncSession`.** `revoke_all_for_user()` was first written as a bulk `UPDATE`, mirroring `SqlaOutboxRepository`'s direct-SQL style, and went through three separate real failures trying to make it work correctly against an already-loaded `ApiKey` object in the same session:

1. `update(api_keys_table)` (the raw Core `Table`, not the mapped class) -- SQLAlchemy never recognizes this as an ORM-enabled bulk update, so it never syncs already-loaded objects at all; an `ApiKey` loaded earlier in the same session/test silently kept a stale `revoked_at`/`is_revoked`, confirmed by a real failing test (`found_a1.is_revoked` reading `False` right after `revoke_all_for_user()` + `commit()`).
2. `update(ApiKey)` (the mapped class) with `synchronize_session="fetch"` -- correctly identifies the right rows, but `"fetch"` *expires* the matched in-memory objects rather than refreshing them immediately, deferring the actual reload to whenever an expired attribute is next accessed. On an `AsyncSession` that deferred reload is an implicit, un-awaited lazy load, crashing with `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called` the instant later plain, synchronous code (e.g. `found_a1.is_revoked` in a later assertion) touches the expired attribute outside an explicitly awaited call -- also confirmed by a real failing test.
3. `synchronize_session="evaluate"` instead of `"fetch"` -- avoids the expiry/lazy-load problem (it updates matched in-memory objects directly, in pure Python, no further DB access), but requires the WHERE clause's columns to carry ORM annotations that only exist when the clause is built from the mapped class's instrumented attributes (e.g. `ApiKey.user_id`), not from the raw `api_keys_table.c.user_id` this code was using -- raising `sqlalchemy.orm.evaluator.UnevaluatableError: Cannot evaluate column: api_keys.user_id`, again confirmed by a real failing test, not a defensive guess.

**The actual, final fix: abandon the bulk `UPDATE` entirely for a plain load-then-mutate loop.** `revoke_all_for_user()` now does `select(ApiKey).where(...)`, then calls the same, already-tested `api_key.revoke(now=...)` on each result in a normal Python loop, then relies on the ordinary flush-on-commit every other single-entity mutation in this codebase already uses. There is then only ever one copy of each key's state -- the loaded ORM object itself -- so there is nothing to keep synchronized with a separate SQL statement, and none of the three failure modes above can occur. This trades a marginal, never-realized performance benefit (one `UPDATE` statement vs. one `SELECT` plus N in-memory mutations) for materially higher correctness confidence, which is the right tradeoff at this deployment's actual scale (realistically a handful of keys per user, not thousands). Any future bulk `UPDATE`/`DELETE` against a mapped entity's table on an `AsyncSession` -- including `docs/plans/9-organizations.md`'s own membership-management commands, if any end up wanting one -- should default to this same load-then-mutate shape unless there's a proven, measured need for true bulk SQL; if there is, budget real time for `synchronize_session` and greenlet/asyncio subtleties, not just a quick `execution_options()` tweak.

**Step 4 -- `ApiKeyIdentityProvider` + `ApiKeyAccessRevoker`.**
- Test: `tests/unit/outbound/adapters/test_api_key_identity_provider.py` -- fakes for `ApiKeyRepository`/`ApiKeyHasher`/`UtcTimer`/`TransactionManager`, a real minimal `starlette.requests.Request`: valid/present/unexpired/unrevoked key resolves to the right `UserId`, and the fake `ApiKeyRepository`'s stored `ApiKey` now shows `use_count` incremented and `commit()` called exactly once; missing header, unknown hash, revoked key, and expired key all raise `ApiKeyAuthenticationError` **without** calling `record_use()`/`commit()` (a failed authentication is not a "use").
- Test: `tests/unit/outbound/adapters/test_api_key_access_revoker.py` -- fake `ApiKeyRepository`/`TransactionManager`: `remove_all_user_access()` calls `revoke_all_for_user()` then `commit()`, in that order.
- Production: `outbound/adapters/api_key_identity_provider.py`, `outbound/adapters/api_key_access_revoker.py`.

**Step 5 -- `PublicApiProvider` (infra-only bindings) + `make_public_api_app()`.**
At this point no interactors exist yet, so `PublicApiProvider` only declares the bindings every one of them will eventually need: `user_service`, `provide_password_hasher`, `identity_provider`, `access_revoker`, `authz_user_finder`, `user_finder`, `utc_timer`, `tx_manager`, `api_key_repository`, `api_key_reader`, `provide_api_key_hasher`.
- Test: `tests/integration/with_infra/api_keys/test_provider_container.py` -- builds `make_public_api_app()` for real (real Postgres), resolves `CurrentUserService`, `ApiKeyRepository`, `ApiKeyReader`, `IdentityProvider`, `AccessRevoker` inside `async with container() as rc` without error.
- Production: `main/ioc/public_api.py` (partial `PublicApiProvider` + `get_public_api_providers()`), `main/run_public_api.py::make_public_api_app()` only, `inbound/http/public_api/router.py::make_public_router()` (empty -- no leaf routers yet).

**Step 6 -- Mounting + always-on public docs (`make_app_with_public_api()`).**
Proves the mounted-sub-app lifespan composition works, before any real business endpoint exists on top of it.
- Test: `tests/integration/with_infra/api_keys/test_public_docs_availability.py` -- builds `make_app_with_public_api(app_settings=AppSettings(ENVIRONMENT="production"))`; asserts `GET /public/docs`/`GET /public/redoc` return `200` (always-on); asserts `GET /docs` on the same combined app returns `404` (still gated, proving `make_app()` itself is untouched); asserts `GET /public/openapi.json` returns `200` with `response.json()["info"]["title"] == "Public API"` to prove the public container actually opened and requests really reach its own mounted routing, not just an outer-prefix match that silently fails to route anywhere -- **adjusted from the originally-sketched `GET /public/v1/api-keys/` → `401` check**, since no leaf router exists yet at this step (that route only appears from Step 7 onward); uses `asgi_lifespan.LifespanManager` to start and cleanly stop the combined app twice in one test, proving the public container's teardown isn't skipped or double-invoked.
- Production: `main/run_public_api.py::make_app_with_public_api()`.

**Step 7 -- `IssueApiKey`.**
- Test: `tests/unit/core/commands/api_keys/test_issue_api_key.py` -- fakes (`tests/unit/core/commands/api_keys/factories.py`) for `UserFinder`/`ApiKeyRepository`/`UtcTimer`/`ApiKeyHasher`, real `UserService`+`StubPasswordHasher` (reused from `tests/unit/core/common/services/stubs.py`): correct credentials return a response with the raw key and right expiry; the repository receives only the *hash*, never the raw key; unknown username and wrong password both raise `InvalidApiKeyCredentialsError` with the same message (enumeration-safety, same principle `CliIdentityProvider` already established); inactive user raises the same exception type with a distinct message; out-of-range `expires_in_days` raises `BusinessTypeError` before anything is persisted.
- Test: `tests/integration/with_infra/api_keys/test_issue_api_key.py` -- `POST /public/v1/api-keys/` against `it_public_client`: `201` with `raw_key` present; the corresponding DB row's `key_hash` column is **not** the raw key; wrong password/unknown username → `401`; inactive account → `401`; out-of-range `expires_in_days` → `400`.
- Production: `core/commands/api_key_exceptions.py`, `core/commands/issue_api_key.py`; add `issue_api_key = provide(IssueApiKey)` to `PublicApiProvider`; `inbound/http/public_api/api_keys/issue_api_key.py` + registration in `api_keys/router.py`/`public_router.py`.

**Step 8 -- `ListApiKeys`.**
- Test: `tests/unit/core/queries/test_list_api_keys.py` -- fake `CurrentUserService`/`ApiKeyReader`: scopes the reader call to `current_user.id_`; pagination/sorting params pass through unchanged.
- Test: `tests/integration/with_infra/api_keys/test_list_api_keys.py` -- issues two keys for user A (one then revoked) and one for user B; `GET /public/v1/api-keys/` with A's key returns only A's two keys (never B's, never `key_hash`); missing/invalid/expired/revoked `X-API-Key` → `401`.
- Production: `core/queries/list_api_keys.py`; add `list_api_keys = provide(ListApiKeys)` to `PublicApiProvider`; `inbound/http/public_api/api_keys/list_api_keys.py` + registration.

**Step 9 -- `RevokeApiKey`.**
- Test: `tests/unit/core/commands/api_keys/test_revoke_api_key.py` -- fake `CurrentUserService`/`ApiKeyRepository`/`UtcTimer`/`TransactionManager`: owner revoking their own key commits a revoked key; unknown id raises `ApiKeyNotFoundError`; another user's key raises `AuthorizationError`; revoking an already-revoked key is a no-op (no second commit).
- Test: `tests/integration/with_infra/api_keys/test_revoke_api_key.py` -- `DELETE /public/v1/api-keys/{id}/` with the owner's key → `204`, and that key subsequently fails authentication; another user's key id → `403`; unknown id → `404`; repeated revoke → `204` again (idempotent).
- Production: `core/commands/revoke_api_key.py` (adds `ApiKeyNotFoundError` to Step 7's exceptions file); add `revoke_api_key = provide(RevokeApiKey)` to `PublicApiProvider`; `inbound/http/public_api/api_keys/revoke_api_key.py` + registration.

**Step 9a -- `GetApiKeyUsageStats`: the analytics query vertical.** (kept adjacent to Step 9 since both are by-id `ApiKey` operations sharing the same 404/403 convention; numbered `9a` rather than renumbering every later step)
- Test: `tests/unit/core/queries/test_get_api_key_usage_stats.py` -- fake `CurrentUserService`/`ApiKeyReader`: happy path returns the reader's `ApiKeyUsageStatsQm` unchanged; unknown id → `ApiKeyNotFoundError`; a stats row whose `user_id` doesn't match the current user → `AuthorizationError`.
- Test: `tests/integration/with_infra/api_keys/test_get_api_key_usage_stats.py` -- issue a key, make two authenticated requests with it against `GET /v1/api-keys/` (**adjusted from the originally-sketched two calls to `GET /public/v1/account/profile/`** -- `GetOwnProfile`/`/account/profile/` doesn't exist until Step 11; `ListApiKeys` is the only authenticated GET route that exists at this point in the plan, and it exercises the exact same `ApiKeyIdentityProvider.record_use()` path either way), then `GET /v1/api-keys/{id}/usage/` with a valid key for the same account → `200` with `use_count == 3` (the two `ListApiKeys` calls *plus* this usage-check request itself, per the self-referential-increment note above) and `last_used_at` set; a fresh key with `use_count == 0`/`last_used_at is None` before its first use; another user's key id → `403`; unknown id → `404`; response body never contains `user_id` or `key_hash`.
- Production: `core/queries/get_api_key_usage_stats.py`; `core/queries/ports/api_key_reader.py`'s `ApiKeyUsageStatsQm`/`get_usage_stats_by_id()` and `outbound/adapters/sqla_api_key_reader.py`'s implementation of it **were already built ahead, in Step 3** (see that step's own test coverage) -- the only new production code this step needs is the interactor itself, plus wiring: add `get_api_key_usage_stats = provide(GetApiKeyUsageStats)` to `PublicApiProvider`; `inbound/http/public_api/api_keys/get_api_key_usage_stats.py` + registration in `api_keys/router.py`.

**Step 10 -- removed.** Was going to add `ChangeOwnPassword` (a public-API password-change command). Removed because an API key shouldn't be able to change the account's login password -- of all the public-API use cases, only `IssueApiKey` actually needs a password, and letting a leaked key do more than "mint/list/revoke keys" is too big a privilege jump. It also would have meant touching the private app's already-working `ChangePassword` for little benefit. `outbound/auth_ctx/handlers/change_password.py` stays untouched, the only password-change surface in this codebase. Numbering keeps the gap, same as Step 9a not being folded into a renumbered Step 10.

**Step 11 -- `GetOwnProfile`, wired into both apps: the cookie-vs-API-key parity proof.**
- Test: `tests/unit/core/queries/test_get_own_profile.py` -- fake `CurrentUserService`: returns a `UserQm` matching whatever user it resolves to; no other dependencies, no `authorize()` call.
- Test: `tests/integration/with_infra/account/test_get_profile.py` -- `GET /api/v1/account/profile/` against the existing `it_client` after the existing `authenticate()` cookie-login helper -- `200` with the signed-up user's own `UserQm`; no cookie -- `401`.
- Test: `tests/integration/with_infra/api_keys/test_get_profile.py` -- `GET /public/v1/account/profile/` against `it_public_client` with a freshly `IssueApiKey`-issued `X-API-Key` -- `200`; asserts the response body is identical (same fields, same values) to the private test's response for the same underlying account -- this is the concrete "same thing works either way" proof; missing/invalid/revoked key -- `401`.
- Production: `core/queries/get_own_profile.py`; one new `get_own_profile = provide(GetOwnProfile)` line in **both** `main/ioc/core.py::CoreProvider` and `main/ioc/public_api.py::PublicApiProvider`; `inbound/http/account/profile.py` + one new registration line in `inbound/http/account/router.py::make_account_router()`; `inbound/http/public_api/account/profile.py` + registration in the already-new `public_api/account/router.py`.

**Step 12 -- End-to-end: deactivating a user auto-revokes all of that user's API keys.**
Exercises `ApiKeyAccessRevoker` for real, through `CurrentUserService`, the same way `AuthSessionAccessRevoker` already gets exercised by the existing (unmodified) deactivation flow.
- Test: `tests/integration/with_infra/api_keys/test_inactive_user_revokes_keys.py` -- a user issues two keys via the public app; separately, an admin deactivates that user via the **existing, unmodified** `DELETE /api/v1/users/{user_id}/activation/` on the **private** app; a subsequent `GET /public/v1/api-keys/` (and `GET /public/v1/account/profile/`) using either of that user's keys returns `401`; a direct DB check confirms both key rows now have `revoked_at` set.
- Production: none -- pure verification that Steps 1-11's pieces (including 9a) compose correctly.

**Step 13 -- Dependency, docs, and roadmap/README checklist sync. Done.**
- **Confirmed: no `pyproject.toml`/`uv.lock` change** -- the entire feature uses only stdlib (`secrets`, `hmac`, `hashlib`) plus dependencies already present (FastAPI, Dishka, SQLAlchemy, Pydantic).
- `docker-entrypoint.sh` -- the `start)` case's uvicorn target now points at `app.main.run_public_api:make_app_with_public_api` instead of `app.main.run:make_app`. Without this one-line swap, everything built in Steps 1-12 would be fully tested but unreachable in any real running deployment -- the private app's own boot command has no knowledge the public API mount exists. Four wiki pages that quoted the old command verbatim (`api-reference.md`, `development-guide/docker-development.md`, `getting-started/quick-start-local.md`, `infrastructure-services/database.md`) were updated alongside it, for the same reason.
- `docs/plans/0-production-readiness-roadmap.md` and `README.md`'s TODO checklists -- both flipped to done, pointing back at this plan file.
- Wiki documentation added: a new page, [`docs/wiki/content/core-patterns/public-api.md`](../wiki/content/core-patterns/public-api.md) (the `X-API-Key` mechanism, the endpoints actually shipped -- issue/list/revoke/usage/profile, deliberately **not** change-password, see Step 10 -- the one-time-reveal raw key, and the always-on `/public/docs`), plus an update to [`docs/wiki/content/core-patterns/dependency-injection.md`](../wiki/content/core-patterns/dependency-injection.md) explaining the "one web process, two Dishka containers" model this feature introduced (`PublicApiProvider` mounted alongside `CoreProvider`, distinct from the Celery worker's genuinely separate OS process).

---

## File Summary

| File | Purpose |
|---|---|
| `src/app/core/common/entities/api_key.py` | `ApiKey` entity: revocation/expiry business rules |
| `src/app/core/common/value_objects/api_key_expiry_days.py` | Bounds-checked caller-chosen expiry |
| `src/app/core/common/ports/api_key_hasher.py` | New port: deterministic, fast key hashing |
| `src/app/core/common/factories/api_key_id_factory.py` / `raw_api_key_factory.py` | uuid7 id / high-entropy raw key generation |
| `src/app/core/commands/ports/api_key_repository.py` | Command-side `ApiKey` repository port |
| `src/app/core/commands/api_key_exceptions.py` | `InvalidApiKeyCredentialsError`, `ApiKeyNotFoundError` |
| `src/app/core/commands/issue_api_key.py` / `revoke_api_key.py` | Issue/revoke commands |
| `src/app/core/queries/ports/api_key_reader.py`, `list_api_keys.py` | The query port + query |
| `src/app/core/queries/get_api_key_usage_stats.py` | `GetApiKeyUsageStats` -- the analytics vertical (`use_count`/`last_used_at`) |
| `src/app/core/queries/get_own_profile.py` | `GetOwnProfile` -- bound into both `CoreProvider` and `PublicApiProvider` unmodified |
| `src/app/inbound/http/account/profile.py` (+ 1 line in `account/router.py`) | Private `GET /api/v1/account/profile/` |
| `src/app/inbound/http/public_api/account/profile.py` | Public `GET /public/v1/account/profile/` |
| `src/app/main/ioc/core.py` (+1 line) | Registers `GetOwnProfile` on the existing `CoreProvider` |
| `src/app/outbound/adapters/hmac_sha256_api_key_hasher.py` | `ApiKeyHasher` adapter |
| `src/app/outbound/adapters/sqla_api_key_repository.py` / `sqla_api_key_reader.py` | Persistence adapters |
| `src/app/outbound/adapters/api_key_identity_provider.py` | `IdentityProvider` via `X-API-Key` |
| `src/app/outbound/adapters/api_key_access_revoker.py` | `AccessRevoker`: revokes this user's keys |
| `src/app/outbound/persistence_sqla/mappings/api_key.py` + new migration | `api_keys` table |
| `src/app/main/ioc/public_api.py` | `PublicApiProvider`: `CoreProvider`-equivalent for the public API |
| `src/app/main/run_public_api.py` | `make_public_api_app()`, `make_app_with_public_api()` |
| `src/app/inbound/http/public_api/**` | The public router group (keys + account password + profile) |
| `docker-entrypoint.sh` | One-line uvicorn target swap (the only way to make this reachable) |
| `src/app/outbound/persistence_sqla/mappings/all.py` | One-line registration of the new mapping |
| `docs/plans/0-production-readiness-roadmap.md`, `README.md` | Checklist sync |

## Verification Plan

- **`make check`** -- lint (`ruff`/`mypy --strict`/`lint-imports`/`slotscheck`) + fast unit tests (Steps 1, 2, 4, 7-11's unit tests). `lint-imports` specifically confirms: `core.commands`/`core.queries` still don't cross-import each other; the new `outbound/adapters/*` files don't import `outbound.auth_ctx` (unaffected either direction); and the `clean-architecture` layers contract still holds with the new `inbound/http/public_api/` package.
- **`make test-docker`** -- full integration suite, including every new `tests/integration/with_infra/api_keys/test_*.py`, `tests/integration/with_infra/account/test_get_profile.py`, and the untouched pre-existing suites (proving nothing regressed for the private app).
- **Manual verification**, using real entrypoints:
  1. `make upd` to bring the stack up.
  2. Sign up a real account through the **private** app's existing flow (Swagger at `http://localhost:8000/docs` in development).
  3. Confirm `http://localhost:8000/public/docs` is reachable and shows the `api-keys`/`account` endpoints, **including with `ENVIRONMENT=production`** in `.secrets` (restart the stack to pick it up) -- while `http://localhost:8000/docs` itself 404s in that mode, proving the two docs pages are genuinely independent.
  4. `curl -X POST http://localhost:8000/public/v1/api-keys/ -d '{"username": "...", "password": "...", "expires_in_days": 30}'` -- confirm a `raw_key` comes back, and repeating the exact same request produces a **different** raw key each time.
  5. `curl http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: <raw_key>"` -- confirm the issued key (and only that account's keys) come back, with no `key_hash` field anywhere in the response.
  6. `curl -X DELETE http://localhost:8000/public/v1/api-keys/<id>/ -H "X-API-Key: <raw_key>"` then repeat step 5 with the same key -- confirm `401`.
  6a. **Usage analytics**: issue a fresh key, make a couple of requests with it (e.g. repeat step 5 twice), then `curl http://localhost:8000/public/v1/api-keys/<id>/usage/ -H "X-API-Key: <raw_key>"` -- confirm `use_count` reflects those prior requests plus this one, `last_used_at` is recent, and the response contains no `user_id`/`key_hash` field; repeat with a different account's key id and confirm `403`.
  7. **Cookie-vs-API-key parity, the specific check the user asked for**: log in through the private app's existing `/api/v1/account/login/` (cookie), then `curl -b <cookie jar> http://localhost:8000/api/v1/account/profile/` -- confirm `200` with the account's profile. Separately, `curl http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: <raw_key>"` for the same account -- confirm `200` with the **same** profile data, proving the same account can do the same thing (view its own profile) through either auth mechanism.
  8. Open Adminer (`http://localhost:8080`), inspect the `api_keys` table directly, and confirm the `key_hash` column never contains anything resembling any raw key returned above.

  (There is deliberately no password-change step here -- `ChangeOwnPassword` was removed from this plan's scope; see Step 10.)

## Human checks

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3), with copy-pasteable `curl` commands. The public API is mounted under http://localhost:8000/public/, and every route except issuing a key needs the key in an `X-API-Key` header.

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`, and seeding never runs with `ENVIRONMENT=production`.
2. Start from a fresh, freshly seeded database (`make down` discards the old one), with the app on http://localhost:8000:
   ```shell
   make down
   make upd
   ```
   Re-run these to reset. Only a key's hash is stored, so the seed script logs a seeded key's raw value just once, on the run that creates it (checks 5 and 7 read it from that log). The checks also issue and revoke keys, and check 14 fills luke-cage's key limit.
3. Run every command in one terminal, top to bottom. Keys and key ids are random, so a command that issues a key saves the response to a file in `/tmp`, and the commands after it read `raw_key` and `id` from that file into shell variables such as `$PETER_KEY`, then echo them. A Python `KeyError` traceback there means the issue failed; `python3 -m json.tool` on that file shows why. Shell variables last as long as the terminal, and a key lasts its `expires_in_days`, so keys don't go stale between checks. Where a check reuses a variable, it names the check that set it.
4. Checks 3 and 6 also log in with a cookie (`-c` saves it at login, `-b` sends it). A cookie session lasts only 5 minutes without use, so those checks log in at their own start.
5. No check takes its starting state on trust. Each first runs a read-only **Prove** command showing what it relies on, and a check that changes something ends with a command showing the change. Each check's **Acts on:** line names every key and id it uses. Commands that print JSON pipe it through `python3 -m json.tool`, which prints it one field per line.
6. Set the Compose project name, from the repo root:
   ```shell
   PROJECT=$(grep -h '^APP_SERVICE_NAME=' env.example .secrets 2>/dev/null | tail -1 | cut -d= -f2)
   PROJECT=${PROJECT:-$(basename "$PWD")}
   echo "$PROJECT"
   ```
   This reads the Compose project name the same way the Makefile does (`APP_SERVICE_NAME`, last value wins, else the folder name), so the direct `docker compose -p "$PROJECT"` commands below look at the same containers `make upd` started.

### Seeded data (from `scripts/seed_db.py`)

The users and passwords are the existing `SEED_USERS`:
- `peter-parker` (`SpideySense2024!`, email `peter.parker@dailybugle.com`): valid key "Spider-Sense Dev Key", expiring 30 days after seeding.
- `tony-stark` (`ImIronMan#3000`): valid key "Stark Industries CI Key".
- `diana-prince` (`AmazonWarrior$99`): key "Themyscira Legacy Key", already expired (it expired one day before seeding).
- `luke-cage` (`PowerMan2024!`): no keys.
- `jean-grey` (`Phoenix19864202!`): a site ADMIN, used only to list which usernames exist.
- `natasha-romanoff` (valid) and `bruce-wayne` (expired) have seeded keys too; no check uses them.

A seeded key's raw value is only in the `app` container's log, in a line like `Seeded valid API key 'Spider-Sense Dev Key' for peter-parker: ak_...`. Checks 5 and 7 read it with `docker compose -p "$PROJECT" logs app` (Setup step 6). (`make logs` doesn't work for this: it follows the log and never exits.)

What the status codes mean here:
- `400`: the request itself is invalid (an expiry out of range).
- `401`: no usable credential: a wrong username or password when issuing, or a missing, unknown, expired or revoked key.
- `403`: a valid key, asking about a key id that belongs to another account.
- `404`: no key has that id.
- `409`: the account already holds the maximum number of active keys.

### Checks

1. **Issue a key with a username: 201, and the raw key is shown once.**

   **Why:** issuing a key is this API's login: prove who you are with a username and password once, and get a long-lived key back. The raw key appears in this response only. The server stores just its hash, so it can never show the key again. It's 201 because a new key row was created.

   **Acts on:** a new key for peter-parker, saved in `$PETER_KEY`, with its id in `$PETER_KEY_ID`.
   ```shell
   curl -s -o /tmp/peter-key.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!", "expires_in_days": 30, "label": "Manual check key"}'
   python3 -m json.tool /tmp/peter-key.json
   PETER_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/peter-key.json"))["raw_key"])')
   PETER_KEY_ID=$(python3 -c 'import json; print(json.load(open("/tmp/peter-key.json"))["id"])')
   echo "$PETER_KEY $PETER_KEY_ID"
   ```
   Expect `201`, then a body with `id`, `raw_key` (starting `ak_`), `"label": "Manual check key"`, `created_at`, and `expires_at` 30 days later, then the key and id echoed. **Prove** the key was stored, by listing peter's keys with it:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   echo "${PETER_KEY:0:11}"
   ```
   Expect `"total": 2`: the seeded "Spider-Sense Dev Key" and "Manual check key". The second one's `id` is `$PETER_KEY_ID`, and its `key_prefix` is the first 11 characters of `$PETER_KEY`, as the `echo` prints. There's no `key_hash` anywhere.

2. **Issue a key with an email address: 201.**

   **Why:** `identifier` takes a username or an email, like the cookie login does. `label` is optional and defaults to `null`. Every issue makes a new random key, even for the same account.

   **Acts on:** a new key for peter-parker, saved in `$PETER_EMAIL_KEY`, and `$PETER_KEY` (set by check 1) to compare with.
   ```shell
   curl -s -o /tmp/peter-email-key.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter.parker@dailybugle.com", "password": "SpideySense2024!", "expires_in_days": 7}'
   python3 -m json.tool /tmp/peter-email-key.json
   PETER_EMAIL_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/peter-email-key.json"))["raw_key"])')
   echo "$PETER_EMAIL_KEY"
   echo "$PETER_KEY"
   ```
   Expect `201`, `"label": null` and an `expires_at` 7 days out, then two different keys. **Prove** the new key belongs to the same account, by listing keys with it:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_EMAIL_KEY" | python3 -m json.tool
   ```
   Expect `"total": 3`, including "Manual check key" from check 1.

3. **A wrong password and an unknown account get the same 401.**

   **Why:** if "no such account" and "wrong password" got different answers, a caller could find out which usernames exist. An unknown account is just failed credentials, so it's 401, not 404.

   **Acts on:** `peter-parker`, a real account, and `nobody-here`, which no account has. `$PETER_KEY` is set by check 1.

   **Prove** peter-parker exists, by fetching his profile with his key:
   ```shell
   curl -s http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   ```
   Expect `"username": "peter-parker"`. Next, **prove** `nobody-here` doesn't exist. Log in as `jean-grey`, an admin, and list every username:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/jean-grey.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "jean-grey", "password": "Phoenix19864202!"}'
   curl -s -b /tmp/jean-grey.cookies 'http://localhost:8000/api/v1/users/?limit=100' \
     | python3 -c 'import sys, json; print(sorted(u["username"] for u in json.load(sys.stdin)["users"]))'
   ```
   Expect `200`, then the 15 seeded usernames, with no `nobody-here`. Then try a wrong password, and an unknown account:
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "WrongPassword123!", "expires_in_days": 30}'
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "nobody-here", "password": "WrongPassword123!", "expires_in_days": 30}'
   ```
   Expect `401` both times, with the same `Invalid username or password.`

4. **An expiry out of range: 400, and nothing is stored.**

   **Why:** a key must live 1 to 365 days, so it can neither expire at once nor live forever. The credentials are right, so it isn't 401: it's 400, a bad value in the request. The expiry is checked before a key is generated, so a refused request leaves nothing behind.

   **Acts on:** peter-parker's credentials, and `$PETER_KEY` (set by check 1) to list his keys.

   **Prove** how many keys peter has now:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   ```
   Expect `"total": 3` (the seeded key plus checks 1 and 2). Then ask for 0 days, then 366:
   ```shell
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!", "expires_in_days": 0}'
   curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!", "expires_in_days": 366}'
   ```
   Expect `400` both times, with `Expiry must be between 1 and 365 days.` **Prove** nothing was stored, by listing peter's keys again:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   ```
   Expect `"total": 3` still.

5. **A seeded valid key works: 200, with peter's profile.**

   **Why:** the seed script builds its keys the same way issuing does (a hash plus an 11-character prefix), so a seeded key must authenticate like an issued one. That's what makes the seeded keys usable for manual testing straight after `make upd`. The profile never includes the password hash.

   **Acts on:** peter's seeded "Spider-Sense Dev Key", read from the log into `$SEEDED_PETER_KEY`, and `$PETER_KEY` (set by check 1) to look at it.

   Read the seeded key from the `app` container's log:
   ```shell
   SEEDED_PETER_KEY=$(docker compose -p "$PROJECT" logs app | grep -o 'for peter-parker: ak_[A-Za-z0-9_-]*' | tail -n 1 | cut -d' ' -f3)
   echo "$SEEDED_PETER_KEY"
   ```
   Expect a key starting `ak_`. An empty line means the database wasn't fresh (the log says `Seed API key 'Spider-Sense Dev Key' already exists, skipping.` instead); run Setup step 2 again. **Prove** it's peter's seeded, valid key, by listing his keys with `$PETER_KEY`:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   echo "${SEEDED_PETER_KEY:0:11}"
   ```
   Expect a "Spider-Sense Dev Key" row with `"revoked_at": null`, an `expires_at` about 30 days from seeding, and a `key_prefix` equal to what the `echo` prints. Then fetch the profile with the seeded key:
   ```shell
   curl -s -w '\n%{http_code}\n' http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $SEEDED_PETER_KEY"
   ```
   Expect `200`, with `"username": "peter-parker"`, `"email": "peter.parker@dailybugle.com"` and no password hash.

6. **The same profile through a cookie and through a key.**

   **Why:** an account can do the same self-service things whichever way it signs in. Both profile routes run the same query behind two different identity mechanisms, so they must return the same body.

   **Acts on:** peter-parker's cookie session, and `$PETER_KEY` (set by check 1).

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. Then fetch the profile both ways:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   curl -s http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   ```
   Expect two identical bodies: the same `id`, `"username": "peter-parker"`, `"phone_number": "27821000011"`, `"role": "user"`, `"is_active": true` and the same timestamps.

7. **A seeded expired key: 401.**

   **Why:** an expired key is refused, with the same 401 and message as an unknown key. It's 401 and not 403: the credential itself no longer works, so the caller isn't anyone at all.

   **Acts on:** diana's seeded "Themyscira Legacy Key", read from the log into `$SEEDED_DIANA_KEY`, and a new key for diana issued here into `$DIANA_KEY`, to look at the seeded one.

   Read the seeded key from the log, and issue diana a fresh key:
   ```shell
   SEEDED_DIANA_KEY=$(docker compose -p "$PROJECT" logs app | grep -o 'for diana-prince: ak_[A-Za-z0-9_-]*' | tail -n 1 | cut -d' ' -f3)
   echo "$SEEDED_DIANA_KEY"
   curl -s -o /tmp/diana-key.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "diana-prince", "password": "AmazonWarrior$99", "expires_in_days": 30}'
   DIANA_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/diana-key.json"))["raw_key"])')
   echo "$DIANA_KEY"
   ```
   Expect a seeded key starting `ak_`, then `201` and a second, different key. **Prove** the seeded key has expired and isn't revoked, by listing diana's keys with the fresh one:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $DIANA_KEY" | python3 -m json.tool
   echo "${SEEDED_DIANA_KEY:0:11}"
   ```
   Expect a "Themyscira Legacy Key" row with an `expires_at` in the past, `"revoked_at": null`, and a `key_prefix` equal to what the `echo` prints. Then try the expired key:
   ```shell
   curl -s -w '\n%{http_code}\n' http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $SEEDED_DIANA_KEY"
   ```
   Expect `401`, with `Invalid or expired API key.`

8. **No key, or a made-up key: 401.**

   **Why:** every route except issuing needs a key. A made-up key's hash matches no stored row. Both get the same 401 and message, so a caller learns nothing about which keys exist.

   **Acts on:** no key at all, then `ak_not-a-real-key`, which matches no key. Nothing needs proving: a real key has 43 random characters after `ak_`, so no issue ever produced this one.
   ```shell
   curl -s -w '\n%{http_code}\n' http://localhost:8000/public/v1/account/profile/
   curl -s -w '\n%{http_code}\n' http://localhost:8000/public/v1/account/profile/ -H 'X-API-Key: ak_not-a-real-key'
   ```
   Expect `401` both times, with `Invalid or expired API key.`

9. **Listing shows only my own keys, never a hash.**

   **Why:** the list is scoped to the account the key belongs to, so one account can't see another's keys. Each row shows a `key_prefix` (`ak_` plus 8 characters) to tell keys apart, never the hash.

   **Acts on:** `$PETER_KEY` (set by check 1), and a new key for tony-stark issued here into `$TONY_KEY`.

   Issue tony a key, and **prove** what he holds, by listing his keys with it:
   ```shell
   curl -s -o /tmp/tony-key.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "tony-stark", "password": "ImIronMan#3000", "expires_in_days": 30}'
   TONY_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/tony-key.json"))["raw_key"])')
   echo "$TONY_KEY"
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $TONY_KEY" | python3 -m json.tool
   ```
   Expect `201`, the key, then `"total": 2`: the seeded "Stark Industries CI Key" and the unlabeled key just issued. Then list peter's keys:
   ```shell
   curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
   ```
   Expect `api_keys`, `"total": 3`, `"limit": 20` and `"offset": 0`. The rows are "Spider-Sense Dev Key", "Manual check key" and the unlabeled key from check 2. There's no "Stark Industries CI Key", and no `key_hash` field anywhere.

10. **Usage stats count every successful request, including the one asking: 200.**

    **Why:** each successful authentication adds one to the key's `use_count` and sets `last_used_at`, so you can see which keys are in use. Asking about a key *with that same key* counts as a use too. Asking with another of your keys doesn't touch it. The response never includes `user_id` or `key_hash`.

    **Acts on:** a new key for peter-parker issued here, in `$USAGE_KEY` with its id in `$USAGE_KEY_ID`, and `$PETER_KEY` (set by check 1) to look at it from outside.
    ```shell
    curl -s -o /tmp/peter-usage-key.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!", "expires_in_days": 30, "label": "Usage check key"}'
    USAGE_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/peter-usage-key.json"))["raw_key"])')
    USAGE_KEY_ID=$(python3 -c 'import json; print(json.load(open("/tmp/peter-usage-key.json"))["id"])')
    echo "$USAGE_KEY $USAGE_KEY_ID"
    ```
    Expect `201`, then the key and id. **Prove** the new key is unused, by asking about it with `$PETER_KEY`:
    ```shell
    curl -s "http://localhost:8000/public/v1/api-keys/$USAGE_KEY_ID/usage/" -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
    ```
    Expect `"use_count": 0` and `"last_used_at": null`. Then use the new key once, and ask about it with itself:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $USAGE_KEY"
    curl -s "http://localhost:8000/public/v1/api-keys/$USAGE_KEY_ID/usage/" -H "X-API-Key: $USAGE_KEY" | python3 -m json.tool
    ```
    Expect `200`, then `"use_count": 2` (the profile request plus this one), a `last_used_at` of just now, and no `user_id` or `key_hash` field. **Prove** the count was stored, and that asking from another key doesn't add to it:
    ```shell
    curl -s "http://localhost:8000/public/v1/api-keys/$USAGE_KEY_ID/usage/" -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
    ```
    Expect `"use_count": 2` still.

11. **Usage stats for another account's key: 403.**

    **Why:** you may only look at your own keys. tony's key is valid, so it isn't 401. The key id exists, so it isn't 404. It's 403: a real caller, asking about a key that isn't theirs. This follows the same 404-versus-403 rule as revoking.

    **Acts on:** peter's "Manual check key" (`$PETER_KEY_ID`, set by check 1), asked about with tony's key (`$TONY_KEY`, set by check 9).

    **Prove** that `$PETER_KEY_ID` is peter's, and that `$TONY_KEY` is tony's:
    ```shell
    echo "$PETER_KEY_ID"
    curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_KEY" | python3 -m json.tool
    curl -s http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $TONY_KEY" | python3 -m json.tool
    ```
    Expect the echoed id on peter's "Manual check key" row, then `"username": "tony-stark"`. Then, with tony's key, ask about peter's key:
    ```shell
    curl -s -w '\n%{http_code}\n' "http://localhost:8000/public/v1/api-keys/$PETER_KEY_ID/usage/" -H "X-API-Key: $TONY_KEY"
    ```
    Expect `403`, with `Not authorized.`

12. **Usage stats for an unknown key id: 404.**

    **Why:** no key has this id, so there is nothing to show. The caller's own key is valid, so it isn't 401.

    **Acts on:** `00000000-0000-4000-8000-000000000000`, a made-up id that matches no key, asked about with `$PETER_KEY` (set by check 1). Nothing needs proving: every real key id is a UUIDv7, which starts with the time it was made, so none is all zeros.
    ```shell
    curl -s -w '\n%{http_code}\n' http://localhost:8000/public/v1/api-keys/00000000-0000-4000-8000-000000000000/usage/ -H "X-API-Key: $PETER_KEY"
    ```
    Expect `404`, with `API key not found.`

13. **Revoke a key: 204, it stops working at once: 401, and revoking again is safe: 204.**

    **Why:** revoking is how you shut down a key that leaked, so it must stop working on the very next request. Revoking twice is harmless (idempotent), so a retried request never errors. The `DELETE`s are sent with another of peter's keys, because a revoked key can't authenticate anything, including a second revoke of itself.

    **Acts on:** peter's "Manual check key" (`$PETER_KEY`, id `$PETER_KEY_ID`, both set by check 1), revoked with peter's key from check 2 (`$PETER_EMAIL_KEY`). After this check `$PETER_KEY` no longer works.

    **Prove** `$PETER_KEY` works and isn't revoked:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $PETER_KEY"
    echo "$PETER_KEY_ID"
    curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_EMAIL_KEY" | python3 -m json.tool
    ```
    Expect `200`, then the echoed id on the "Manual check key" row, with `"revoked_at": null`. Then revoke it, try it, and revoke it again:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "http://localhost:8000/public/v1/api-keys/$PETER_KEY_ID/" -H "X-API-Key: $PETER_EMAIL_KEY"
    curl -s -w '\n%{http_code}\n' http://localhost:8000/public/v1/account/profile/ -H "X-API-Key: $PETER_KEY"
    curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "http://localhost:8000/public/v1/api-keys/$PETER_KEY_ID/" -H "X-API-Key: $PETER_EMAIL_KEY"
    ```
    Expect `204`, then `401` with `Invalid or expired API key.`, then `204`. **Prove** the key is marked revoked, by listing peter's keys:
    ```shell
    curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $PETER_EMAIL_KEY" | python3 -m json.tool
    ```
    Expect the "Manual check key" row still listed, now with a `revoked_at` date.

14. **The per-account key limit: 409 once it's reached, and revoking frees a slot: 201.**

    **Why:** `API_KEY_MAX_PER_USER` (default `10`, in `env.example`) caps how many non-revoked keys one account holds, so keys can't pile up unnoticed. Expired keys still count until they're revoked. It's 409, not 400 or 403: the request is fine and the caller is allowed, but the account's current state (full) blocks it. Revoking a key frees its slot, so it isn't a lifetime cap.

    **Acts on:** luke-cage's credentials; his first key, saved in `$LUKE_KEY` with its id in `$LUKE_KEY_ID`; and his tenth, saved in `$LUKE_LAST_KEY`.

    Issue luke's first key:
    ```shell
    curl -s -o /tmp/luke-key-1.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "luke-cage", "password": "PowerMan2024!", "expires_in_days": 1}'
    LUKE_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/luke-key-1.json"))["raw_key"])')
    LUKE_KEY_ID=$(python3 -c 'import json; print(json.load(open("/tmp/luke-key-1.json"))["id"])')
    echo "$LUKE_KEY $LUKE_KEY_ID"
    ```
    Expect `201`, then the key and id. **Prove** luke had no keys before it, by listing his keys:
    ```shell
    curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $LUKE_KEY" | python3 -m json.tool
    ```
    Expect `"total": 1`. Then issue eight more, and a tenth that's saved:
    ```shell
    for i in $(seq 1 8); do
      curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
        -H 'Content-Type: application/json' \
        -d '{"identifier": "luke-cage", "password": "PowerMan2024!", "expires_in_days": 1}'
    done
    curl -s -o /tmp/luke-key-10.json -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "luke-cage", "password": "PowerMan2024!", "expires_in_days": 1}'
    LUKE_LAST_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/luke-key-10.json"))["raw_key"])')
    echo "$LUKE_LAST_KEY"
    ```
    Expect nine `201` lines, then the key. **Prove** luke is at the limit:
    ```shell
    curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $LUKE_LAST_KEY" | python3 -m json.tool
    ```
    Expect `"total": 10`, every row with `"revoked_at": null`. Then try an eleventh:
    ```shell
    curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "luke-cage", "password": "PowerMan2024!", "expires_in_days": 1}'
    ```
    Expect `409`, with `You have reached the maximum number of active API keys.` Then revoke the first key, and try again:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "http://localhost:8000/public/v1/api-keys/$LUKE_KEY_ID/" -H "X-API-Key: $LUKE_LAST_KEY"
    curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/public/v1/api-keys/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "luke-cage", "password": "PowerMan2024!", "expires_in_days": 1}'
    ```
    Expect `204`, then `201`. **Prove** the change, by listing his keys again:
    ```shell
    curl -s http://localhost:8000/public/v1/api-keys/ -H "X-API-Key: $LUKE_LAST_KEY" | python3 -m json.tool
    ```
    Expect `"total": 11`, with exactly one `revoked_at` date: on the row whose `id` is `$LUKE_KEY_ID`.

15. **The public docs are always on: 200.**

    **Why:** an integrating developer must be able to read this API's docs whatever the deployment's `ENVIRONMENT`. The private app's http://localhost:8000/docs is only served in development. The public docs belong to their own mounted app, so that rule doesn't reach them.

    **Acts on:** no key and no data: the docs routes need neither. Nothing needs proving here.
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/public/docs
    curl -s http://localhost:8000/public/openapi.json | python3 -c 'import sys, json; print(json.load(sys.stdin)["info"]["title"])'
    ```
    Expect `200`, then `Public API`, which shows the request reached the public app's own routing. Open http://localhost:8000/public/docs in a browser: it lists the API Keys and Account routes and has an `X-API-Key` field for trying them. To see the two docs pages differ, set `ENVIRONMENT=production` in `.secrets`, run `make down` then `make upd`, and run:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/docs
    curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/public/docs
    ```
    Expect `404`, then `200`. Set `ENVIRONMENT=development` again afterwards (production also turns seeding off).
