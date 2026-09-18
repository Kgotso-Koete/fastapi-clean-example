# Public API (Server-to-Server Clients)

!!! sourcefiles "Relevant Source Files/Folders"
    - [`src/app/main/run_public_api.py`](../../../../src/app/main/run_public_api.py) — `make_public_api_app()` (the standalone public app) / `make_app_with_public_api()` (mounts it onto the private app; this is the function `docker-entrypoint.sh` actually boots)
    - [`src/app/main/ioc/public_api.py`](../../../../src/app/main/ioc/public_api.py) — `PublicApiProvider`, the public API's own, independent Dishka provider set
    - [`src/app/core/common/entities/api_key.py`](../../../../src/app/core/common/entities/api_key.py) — `ApiKey`: revocation/expiry rules, `use_count`/`last_used_at` usage tracking
    - [`src/app/outbound/adapters/api_key_identity_provider.py`](../../../../src/app/outbound/adapters/api_key_identity_provider.py) — `ApiKeyIdentityProvider`, the `IdentityProvider` adapter for this container
    - [`src/app/outbound/adapters/api_key_access_revoker.py`](../../../../src/app/outbound/adapters/api_key_access_revoker.py) — `ApiKeyAccessRevoker`, the `AccessRevoker` adapter for this container
    - [`src/app/outbound/adapters/hmac_sha256_api_key_hasher.py`](../../../../src/app/outbound/adapters/hmac_sha256_api_key_hasher.py) — deterministic key hashing (HMAC-SHA256, not bcrypt — see below)
    - [`src/app/core/commands/issue_api_key.py`](../../../../src/app/core/commands/issue_api_key.py) / [`revoke_api_key.py`](../../../../src/app/core/commands/revoke_api_key.py) — the two key-lifecycle commands
    - [`src/app/core/queries/list_api_keys.py`](../../../../src/app/core/queries/list_api_keys.py) / [`get_api_key_usage_stats.py`](../../../../src/app/core/queries/get_api_key_usage_stats.py) — the two key-lifecycle queries
    - [`src/app/core/queries/get_own_profile.py`](../../../../src/app/core/queries/get_own_profile.py) — `GetOwnProfile`, bound **unmodified** into both this container and `CoreProvider`'s
    - [`src/app/inbound/http/public_api/`](../../../../src/app/inbound/http/public_api/) — every route this API exposes
    - [`docs/plans/8-public-api-key-auth.md`](../../../../docs/plans/8-public-api-key-auth.md) — the full implementation plan and design rationale, including two design decisions this page only summarizes

    > These links resolve when this page is opened as a raw `.md` file in an IDE like VS Code (cmd/ctrl-click follows them straight to the file) — they 404 in the browser here, since the rendered site doesn't serve the source tree itself. That's expected, not a bug.

## What this is

A server-to-server HTTP surface, mounted at `/public`, authenticated by a long-lived `X-API-Key` header instead of a browser session cookie. It's for the same kind of client a Node/Express backend would put behind its own `/public` router: a machine calling in on behalf of an already-registered account, not a human clicking through a UI. It mirrors a handful of the private app's own account use cases (never account creation — an API key can only ever apply to an *already-existing* account) using the exact same `core` interactors where the use case is genuinely identical, and its own, new interactors where it isn't.

## One web process, two Dishka containers — not two processes

The public API is **not** a separate service and does not get its own OS process, the way the Celery worker does. `docker-entrypoint.sh`'s `start` case boots exactly one `uvicorn` process, on one port, running `make_app_with_public_api()`. From outside, this looks like any framework's "mount two routers under one app": one host, one port, `/api/*` and `/public/*` both reachable.

The reason it isn't *literally* one router mounted onto the existing app — the way you might add a second Express router to the same `app` — is [Dishka](https://github.com/reagento/dishka)'s container model, covered in full in [Dependency Injection with Dishka](dependency-injection.md). Dishka validates an entire container's dependency graph at *build time*, and does not allow two different concrete adapters to be bound to the same abstract port within one container. The private app needs `IdentityProvider → AuthSessionIdentityProvider` (cookie sessions) and `AccessRevoker → AuthSessionAccessRevoker`; the public API needs the same two ports bound to `ApiKeyIdentityProvider`/`ApiKeyAccessRevoker` instead. Those pairs of bindings cannot coexist in one Dishka container — so the public API gets its own container, built from `PublicApiProvider`, attached to its own nested Starlette sub-application via `app.mount()`, itself given its own `setup_dishka()` call. Two independent containers, two independent connection pools, one process.

!!! figure "One process, two mounted ASGI apps, two Dishka containers"
    ```mermaid
    %%{init: {"theme": "default", "themeVariables": {"fontSize": "14px"}, "flowchart": {"nodeSpacing": 20, "rankSpacing": 16, "padding": 10, "subGraphTitleMargin": {"top": 5, "bottom": 12}, "useMaxWidth": false}}}%%
    flowchart TB
        subgraph proc["One uvicorn process, one port (make_app_with_public_api)"]
            subgraph priv["Private app -- make_app() (mounted at /)"]
                coreP["CoreProvider"]
                coreC[("AsyncContainer<br/>IdentityProvider -> AuthSessionIdentityProvider")]
            end
            subgraph pub["Public app -- make_public_api_app() (mounted at /public)"]
                pubP["PublicApiProvider"]
                pubC[("AsyncContainer<br/>IdentityProvider -> ApiKeyIdentityProvider")]
            end
        end
        client["Client"] -->|"/api/v1/..."| priv
        client -->|"/public/v1/..."| pub

        linkStyle default stroke-width:3px,stroke:#333333
        style proc stroke-width:1px,stroke:#333333
    ```

    > Both containers open their own `AsyncEngine`/connection pool against the same Postgres — a real, deliberate resource cost (roughly doubling this process's steady-state connection count), accepted at this deployment's scale. Sharing one engine across both containers is a legitimate future optimization, explicitly deferred (see the plan's "two connection pools" section).

This is the same trade-off `WorkerProvider` already made for the Celery worker, just one level shallower: a wholly independent provider set rather than trying to trim or share one graph across two genuinely different binding requirements. Nothing about `CoreProvider`, `AuthProvider`, or any pre-existing wiring changes because this container exists.

## Identity: API keys, not passwords, for almost everything

`IssueApiKey` is the sole exception, and deliberately so — it takes a username/password (mirroring `LogIn`) because at that moment no key exists yet to prove identity with. Every other endpoint (`ListApiKeys`, `RevokeApiKey`, `GetApiKeyUsageStats`, `GetOwnProfile`) authenticates purely via the key itself, through `ApiKeyIdentityProvider`.

Keys are generated with `secrets.token_urlsafe(32)` (256 bits of entropy) behind a fixed `ak_` prefix — the same pattern GitHub/Stripe use, so automated secret-scanners can recognize a leaked key by shape. Only the **hash** is ever persisted (`HmacSha256ApiKeyHasher` — HMAC-SHA256, not bcrypt: the key is already high-entropy, so a slow KDF designed to resist brute-forcing a *low*-entropy human password buys nothing here and would make every authenticated request noticeably slower). The raw key is shown to the caller exactly once, at issuance; `key_prefix` (the first several characters, non-secret) is what `ListApiKeys` shows so a caller can tell keys apart afterward without the raw value ever being persisted or shown again.

## A deliberate scope boundary: no password-change endpoint here

An earlier iteration of this plan added a `ChangeOwnPassword` command, bound into *both* containers like `GetOwnProfile` — reasoning that self-service password change should be as entrypoint-agnostic as viewing your own profile. It was removed. Auditing the public API's actual use cases showed only `IssueApiKey` ever touches a password at all; letting an API key additionally change the account's master login password is a materially bigger privilege than "mint/list/revoke keys of your own kind" — a leaked key should mean "an attacker can call the API," not "an attacker can lock the real account owner out entirely." Making it entrypoint-agnostic would also have meant retiring the private app's existing, working `ChangePassword` (`outbound/auth_ctx/handlers/change_password.py`) for no strong specific reason. That file remains untouched and is the only password-change surface in this codebase. See `docs/plans/8-public-api-key-auth.md`'s Step 10 for the full record of this reversal.

## Usage analytics: a plain counter, not a domain event

`ApiKey.record_use()` bumps `use_count`/`last_used_at` on every successful authentication — called directly from `ApiKeyIdentityProvider`, committed in the same transaction as the request it's authenticating. This is deliberately *not* routed through this codebase's own domain-event/outbox machinery (see [Domain Events & the Transactional Outbox](domain-events-outbox.md)): the side effect never leaves `ApiKey`'s own consistency boundary, so raising, staging, and dispatching an event just to increment a field on the same row that raised it would be the wrong-sized tool. `GetApiKeyUsageStats` (a by-id query, following `RevokeApiKey`'s ownership-check convention rather than `ListApiKeys`'s scoped-query one) exposes `use_count`/`last_used_at` back to the caller — and, notably, checking a key's own usage via that key necessarily bumps its own count by one in the process, the same "the page-view counter increments when you view the page" behavior a naive reading might mistake for a bug.

## Naming: `PublicApiProvider`, not `ApiKeyProvider`

The composition-root provider is named for the **entrypoint it serves** (the public API), matching `CliProvider`/`WorkerProvider`'s own convention — not for the authentication mechanism (API keys) that entrypoint happens to use today. `ApiKeyIdentityProvider` and `ApiKeyAccessRevoker`, by contrast, *are* named after the mechanism, deliberately: they implement generic ports (`IdentityProvider`, `AccessRevoker`) via one specific strategy, the same way `AuthSessionIdentityProvider` is named after sessions, not "the private app's identity provider." If this API ever added a second authentication mechanism, the provider wouldn't need renaming; the adapters correctly would.

## Endpoints

| Method + path | Auth | Interactor | Notes |
|---|---|---|---|
| `POST /public/v1/api-keys/` | None (credentials in body) | `IssueApiKey` | Returns the raw key exactly once |
| `GET /public/v1/api-keys/` | `X-API-Key` | `ListApiKeys` | Caller's own keys only, paginated |
| `DELETE /public/v1/api-keys/{id}/` | `X-API-Key` | `RevokeApiKey` | Idempotent; owner-only (403 for someone else's key id) |
| `GET /public/v1/api-keys/{id}/usage/` | `X-API-Key` | `GetApiKeyUsageStats` | `use_count`/`last_used_at`; owner-only |
| `GET /public/v1/account/profile/` | `X-API-Key` | `GetOwnProfile` | Identical response shape to `GET /api/v1/account/profile/` for the same account — see below |
| `GET /public/docs`, `/public/redoc`, `/public/openapi.json` | None | — | Always reachable, in every `ENVIRONMENT`, unlike the private app's dev-only-gated docs — this API is meant to be integrated against in production |

## The cookie-vs-API-key parity proof

`GetOwnProfile` is bound, completely unmodified, into both `CoreProvider` and `PublicApiProvider`. It depends on nothing but `CurrentUserService`, which itself only knows about the generic `IdentityProvider`/`AccessRevoker` ports — so the *same Python class* serves `GET /api/v1/account/profile/` (cookie) and `GET /public/v1/account/profile/` (API key), each container resolving its own concrete adapters underneath it. `tests/integration/with_infra/api_keys/test_get_profile.py` asserts this concretely: it authenticates as the same account both ways and asserts the two JSON responses are byte-for-byte identical.

## Testing

Public API tests live under [`tests/integration/with_infra/api_keys/`](../../../../tests/integration/with_infra/api_keys/), following [Test Infrastructure & Fixtures](../testing/test-infrastructure.md). `it_public_app`/`it_public_client` (in that directory's own `conftest.py`) build and talk to the **standalone** `make_public_api_app()` directly — endpoint constants in these tests deliberately have no `/public` prefix, since that prefix is only added once `make_app_with_public_api()` mounts this same app onto the private one. A real bug was hit exactly this way early on: an endpoint constant written with the `/public` prefix baked in 404'd against `it_public_client`, because the fixture talks to the unmounted app.

[`test_inactive_user_revokes_keys.py`](../../../../tests/integration/with_infra/api_keys/test_inactive_user_revokes_keys.py) is worth reading on its own: it adds *no* new production code, and instead proves an already-built mechanism composes correctly across both containers — deactivating a user via the private app only revokes that user's *sessions* directly (`CoreProvider`'s own `AccessRevoker`), but the very next attempt to use any of that user's API keys is rejected by `CurrentUserService`'s own inactive-user guard, which then lazily revokes *all* of that user's keys as a side effect, because in the public container that same guard's `AccessRevoker` resolves to `ApiKeyAccessRevoker`.

## Where to go next

- [Dependency Injection with Dishka](dependency-injection.md) — the full container-per-composition-root model, including why the worker needed the same "wholly independent provider" treatment first.
- [Authorization & RBAC](authorization-rbac.md) — `CurrentUserService`'s own authorization shape, shared by every entrypoint.
- [Domain Events & the Transactional Outbox](domain-events-outbox.md) — the machinery `record_use()` deliberately doesn't use, and why.
- `docs/plans/8-public-api-key-auth.md` — the complete, step-by-step implementation record, including every design correction made along the way.
