# User and Organization Search

> **Implementation Plan (proposed, not started)**
>
> Sequenced after `docs/plans/9-organizations.md` is complete -- organization search depends on the `organizations`/`organization_memberships` tables and on `ListMyOrganizations`' scoping rules existing first -- and after the Row-Level Security rollout (see `docs/plans/0-production-readiness-roadmap.md`), because search adds new queries over organization data. Do not begin implementation from this file alone without re-confirming it is still current.

## Context

Almost every application built on this template eventually needs a search box: an admin looking up a user, a member finding one of their organizations, and -- the case that makes search genuinely painful -- **search-as-you-type**, where results update as someone types the first few letters. Today the only way to find anything is the paginated list endpoints (`ListUsers`, and `ListMyOrganizations` once Step 8 of plan 9 lands), which a person has to scroll through.

This plan adds **text search over users and organizations** that follows this template's **smallest-viable-infrastructure principle** (`docs/plans/0-production-readiness-roadmap.md`): it works out of the box on **Postgres alone**, using Postgres's built-in text-search features, and can optionally be switched to **Elasticsearch** by configuration when a deployment outgrows Postgres -- exactly the way domain events run inline by default and optionally via Celery, behind the same ports.

Two matching behaviors are required from the start, because they are what users actually expect from a search box:

1. **Prefix / search-as-you-type** -- typing `ave` finds `Avengers`; typing `ton` finds `tony_stark`. Every word of the query is treated as "starts with", so `mid sun` finds `Midnight Suns`.
2. **Keyword** -- whole words anywhere in the searchable text, in any order, with results ranked so the best match comes first.

Both are served by one query parameter (`q`) and one code path: the query is split into words, and each word matches as a prefix. A complete word is simply a prefix that happens to be a whole word, so keyword search falls out of prefix search rather than needing a separate mode.

Results are **always paginated**, reusing this template's existing `OffsetPaginationParams` (`limit`/`offset`) and the same `{items, total, limit, offset}` response shape every other list endpoint already uses.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Search users | platform admin | to search accounts by the first letters of their username or email | I can find a user without scrolling the whole user list | `ton` finds `tony-stark`; `pet par` finds `peter-parker`<br>Paginated `{items, total, limit, offset}`, best match first, same fields as `ListUsers`<br>A plain user gets 403 |
| 2. Search my organizations | user | to search the organizations I belong to by name as I type | I can jump to one quickly | `ave` finds `Avengers` when I'm an accepted member<br>An organization I only have a pending or expired invitation to never appears<br>`q` under 2 characters gets 400; missing `q` gets 422 |
| 3. Private to members | organization OWNER | my organization never to appear in a non-member's search results | its existence stays private to its members | An outsider searching its exact name gets an empty page (`total` 0), not an error<br>A platform admin gets no global organization directory either<br>Holds on both the Postgres and Elasticsearch backends |

---

## Design

### What is searchable, and who may search it

- **Users** -- searched by `username` (and `email`), **platform-admin only**, exactly the same authorization as the existing `ListUsers` (`CanManageRole` with `target_role=UserRole.USER`). Searching all accounts, and especially searching by email, is an administrative capability, never something an ordinary user gets. The response exposes the same fields `ListUsers` already does -- no new personal data leaves the system.
- **Organizations** -- searched by `name`, **scoped to the caller's own accepted memberships**, exactly the same scoping as `ListMyOrganizations` (plan 9). There is deliberately **no global organization directory**: organizations are private tenants, and a search that returned organizations the caller doesn't belong to would be a cross-tenant leak -- precisely the failure mode plan 9's "Defense in depth" section exists to prevent. This scoping rule applies to *both* backends (see "Elasticsearch" below for why it needs special care there).
- **Out of scope for now:** searching an organization's members (a natural follow-up, gated at `OrganizationRole.MEMBER` like `ListOrganizationMembers`), and searching any future business-domain resource. Both reuse the same `SearchQuery` value object and port shape this plan establishes.

### `SearchQuery` -- a value object, validated in the domain

`src/app/core/common/value_objects/search_query.py` (new). The raw `q` string is never passed to a database or search engine directly:

- trimmed; **minimum 2 characters** after trimming (a 1-letter prefix matches almost everything and is expensive); **maximum 100 characters**;
- split into **word tokens** (letters and digits only -- every other character acts as a separator), at most a small fixed number of tokens (e.g. 5);
- exposes the tokens, never the raw string, to adapters.

Tokenizing in the value object is also the injection defense: Postgres `to_tsquery()` has its own operator syntax (`&`, `|`, `!`, `:*`, parentheses), and passing raw user text into it can raise syntax errors or change the query's meaning. Because adapters only ever receive clean alphanumeric tokens, each adapter builds its engine-specific query from known-safe pieces.

### The port, and its two adapters

`src/app/core/queries/ports/user_search.py` and `organization_search.py` (new, query side -- search is a read). One method each:

```python
class UserSearch(Protocol):
    @abstractmethod
    async def search_users(self, query: SearchQuery, *, pagination: OffsetPaginationParams) -> SearchUsersQm: ...


class OrganizationSearch(Protocol):
    @abstractmethod
    async def search_organizations_for_user(
        self, user_id: UserId, query: SearchQuery, *, pagination: OffsetPaginationParams
    ) -> SearchOrganizationsQm: ...
```

Results are ordered by relevance first, then by `id` as a stable tie-breaker (the same tie-breaker convention `SqlaApiKeyReader`/`SqlaOrganizationReader` already use), so pagination never shuffles rows between pages.

**Default adapter -- Postgres, zero new infrastructure** (`PostgresUserSearch`, `PostgresOrganizationSearch`):

- Uses Postgres's built-in **full-text search** with the `simple` text-search configuration (no stemming and no stop words -- names and usernames aren't prose, so English stemming would only cause surprising matches). Each token becomes a prefix term (`token:*`), combined with AND: `to_tsvector('simple', <column>) @@ to_tsquery('simple', 'mid:* & sun:*')`, ranked with `ts_rank`.
- Indexed with a **GIN expression index** on `to_tsvector('simple', <column>)` -- an index only, **no new column** on any table. This matters for the users table in particular: it is the original template author's schema, and an expression index is the purely additive way to make it searchable (dropping the index restores it exactly, which is this project's feature-delete test).
- **To verify in Step 2's spike before committing to it:** how Postgres's default text parser tokenizes usernames and emails containing `.`, `-` and `_` (e.g. whether `tony_stark` is indexed as one token or two). If the built-in parser splits them in a way that breaks prefix matching on a username, the fallback -- still built into standard Postgres images -- is the `pg_trgm` extension with a trigram GIN index, which does substring matching on the raw string. The spike decides between the two; the port and tests don't change either way.
- Reference: https://www.postgresql.org/docs/current/textsearch.html and https://www.postgresql.org/docs/current/pgtrgm.html

**Optional adapter -- Elasticsearch** (`ElasticsearchUserSearch`, `ElasticsearchOrganizationSearch`), selected by a new `SEARCH_BACKEND=postgres|elasticsearch` setting (default `postgres`):

- Uses a `search_as_you_type` field for names/usernames, queried with a `bool_prefix` multi-match, which gives prefix-on-every-word plus relevance ranking natively. Reference: https://www.elastic.co/guide/en/elasticsearch/reference/current/search-as-you-type.html
- **Index synchronization is the real cost of this backend**, and it reuses this template's existing machinery rather than inventing new machinery: a user's or organization's search document is written by an event handler on the relevant domain events (`UserRegisteredEvent` exists today; organization created/renamed events would be added alongside), dispatched in `"background"` mode through the existing transactional outbox so a crash can't silently drop an index update. Search results under this backend are therefore **eventually consistent** -- a just-created organization may take a moment to appear. A CLI command (`make cli args="search reindex"`) rebuilds the whole index from Postgres, for first-time setup and recovery.
- **Tenant scoping must still hold.** Organization documents carry the ids of their accepted members, and every organization query filters on the caller's id. This filter is not optional and gets its own cross-tenant test (Step 6), because -- unlike Postgres -- Elasticsearch can't be protected by the Row-Level Security layer plan 9 proposes.
- Runs as an **optional Docker Compose service** under its own `search` profile, following the same opt-in pattern the `celery` profile already uses, so deployments that stay on Postgres never run (or pay for) an Elasticsearch node.

### HTTP routing shape

A new, self-contained router group -- one `include_router` line in `api_v1_router.py` is the only touch to existing routing:

```
GET /api/v1/search/users/?q=ton&limit=10&offset=0            SearchUsers         (platform admin)
GET /api/v1/search/organizations/?q=ave&limit=10&offset=0    SearchMyOrganizations (caller's own organizations)
```

`q` shorter than the minimum returns **400** (`BusinessTypeError` from `SearchQuery`, the same mapping every other value object uses); a missing `q` returns FastAPI's **422**. Search-as-you-type clients typically request a small `limit` (e.g. 10) and debounce keystrokes on their side.

### Deliberately out of scope

- **Fuzzy / typo-tolerant matching** (`tomy` finding `tony`). Elasticsearch can do it; Postgres needs `pg_trgm` similarity. A real enhancement, but not required for prefix and keyword search.
- **Highlighting** the matched part of each result.
- **Keyset (cursor) pagination.** Offset pagination is consistent with the rest of this template, and search results are rarely paged deeply.
- **A generic "search anything" endpoint.** Each resource gets its own explicitly authorized search, so scoping rules can never be forgotten for one resource type.

---

## Package layout

```
src/app/core/common/value_objects/search_query.py
src/app/core/queries/ports/user_search.py                 # UserSearch, SearchUsersQm
src/app/core/queries/ports/organization_search.py         # OrganizationSearch, SearchOrganizationsQm
src/app/core/queries/search_users.py
src/app/core/queries/search_my_organizations.py

src/app/outbound/adapters/postgres_user_search.py
src/app/outbound/adapters/postgres_organization_search.py
src/app/outbound/adapters/elasticsearch_user_search.py
src/app/outbound/adapters/elasticsearch_organization_search.py
src/app/outbound/persistence_sqla/alembic/versions/<ts>_add_search_indexes.py   # GIN expression indexes only

src/app/inbound/http/search/router.py                    # make_search_router()
src/app/inbound/http/search/search_users.py
src/app/inbound/http/search/search_my_organizations.py

src/app/main/config/settings.py                           # + SearchSettings (SEARCH_BACKEND, Elasticsearch URL)
```

Additive touches to existing files: the new bindings in `CoreProvider` (chosen by `SEARCH_BACKEND`, the way `provide_email_sender` already chooses between console and SMTP); one `include_router` line in `api_v1_router.py`; the new settings class and its loader; an optional `elasticsearch` service in `docker-compose.yml` under a `search` profile (with fallback defaults on every env interpolation); `env.example`.

---

## Proposed Changes

Test file(s) before production file(s) per step, per this project's TDD convention.

**Step 1 -- `SearchQuery` value object.**
- Test: `tests/unit/core/common/value_objects/test_search_query.py` -- trims; rejects blank, 1-character and over-length input; splits on non-alphanumeric characters; drops empty tokens; caps the token count; never exposes `to_tsquery` operator characters in any token.
- Production: `search_query.py`.

**Step 2 -- Spike: Postgres tokenization of usernames/emails/organization names.**
- Test: a small, isolated integration test proving (or disproving) that `to_tsvector('simple', ...)` + `token:*` prefix queries find `tony_stark` from `ton`, `peter.parker` from `pet`, and `Midnight Suns` from `mid sun`. Decide full-text vs. `pg_trgm` here, and record the decision in this plan.

**Step 3 -- `PostgresUserSearch` + the users expression index migration.**
- Test: `tests/integration/with_infra/search/test_postgres_user_search.py` -- prefix and keyword matches; ranking puts the better match first; pagination with a correct `total` on every page; no match returns an empty page with `total == 0`.
- Production: the port, the adapter, the migration (generated with `make migration msg="..."`, never hand-written).

**Step 4 -- `SearchUsers` query + `GET /api/v1/search/users/`.**
- Test: unit (admin-only, reusing `ListUsers`' authorization; request passes through unchanged) + integration (200 for an admin; 401 unauthenticated; 403 for a plain user; 400 for a too-short `q`; 422 for a missing `q`).
- Production: the query, the route, the router registration, the provider binding.

**Step 5 -- `PostgresOrganizationSearch` + index, `SearchMyOrganizations` + `GET /api/v1/search/organizations/`.**
- Test: integration -- only the caller's own **accepted** organizations are ever returned (a pending invitation's organization and a stranger's organization never appear, even when their names match); unit + HTTP tests as in Step 4.
- Production: the port, adapter, migration, query, route, binding.

**Step 6 -- `SearchSettings` + the Elasticsearch adapters.**
- Test: `test_loader.py` env-var test for `SEARCH_BACKEND` and the Elasticsearch URL (every new setting gets one, per this project's convention); integration tests for both Elasticsearch adapters, including a dedicated **cross-tenant organization test**, marked so they only run when the `search` profile's Elasticsearch service is up (a separate make target, so `make test-docker` doesn't require Elasticsearch).
- Production: settings, both adapters, the backend-selecting provider, the Compose service.

**Step 7 -- Index synchronization + reindex CLI (Elasticsearch backend only).**
- Test: unit tests for the index-sync event handlers; integration test that creating a user/organization produces a search document via the outbox; CLI test for `search reindex`.
- Production: the handlers, the organization events they need, the CLI command.

**Step 8 -- Docs, roadmap and README sync.**
- Wiki page covering both backends, how to switch, the eventual-consistency trade-off of Elasticsearch, and how to add search to a new resource using the same `SearchQuery` + port shape.
- `docs/plans/0-production-readiness-roadmap.md` and `README.md` -- mark done in the style of the other completed items.

---

## File Summary

- `src/app/core/common/value_objects/search_query.py` -- validates and tokenizes the raw `q`
- `src/app/core/queries/ports/user_search.py`, `organization_search.py` -- the two search ports
- `src/app/core/queries/search_users.py`, `search_my_organizations.py` -- the two queries (authorization + scoping)
- `src/app/outbound/adapters/postgres_*_search.py` -- default, Postgres-only adapters
- `src/app/outbound/adapters/elasticsearch_*_search.py` -- optional Elasticsearch adapters
- `.../alembic/versions/<ts>_add_search_indexes.py` -- GIN expression indexes (no schema changes)
- `src/app/inbound/http/search/**` -- the search router group
- `src/app/main/config/settings.py` (+`SearchSettings`), `src/app/main/ioc/core.py` (+bindings), `docker-compose.yml` (+optional `elasticsearch` service), `env.example`

## Verification Plan

- **`make check`** -- lint, `mypy --strict`, `lint-imports` (search ports stay on the query side; `core` never imports an Elasticsearch client), unit tests.
- **`make test-docker`** -- full integration suite on the default Postgres backend, which needs no new infrastructure.
- **The Elasticsearch test target** (added in Step 6) -- the Elasticsearch adapter suite, including the cross-tenant test, with the `search` profile running.
- **Manual verification**, using real entrypoints and the seeded superhero data: as an admin, type `ton`, then `tony`, and see the user list narrow; as a seeded user, search `ave` and see only organizations you belong to; confirm a pending invitation's organization does not appear; switch `SEARCH_BACKEND=elasticsearch`, run `make cli args="search reindex"`, and confirm the same searches return the same results.

---

## Human checks

(planned -- to run once this plan is implemented; commands follow the routes this plan defines)

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3). The users, passwords and organizations are the ones listed in `docs/plans/9-organizations.md`'s "Human checks" section and `scripts/seed_db.py`. Note that seeded usernames use hyphens (`tony-stark`, `peter-parker`), which is exactly what Step 2's tokenization spike has to handle.

Two details the plan leaves open, so check the result against the rule rather than an exact value:
- **The name of the results list.** The plan says `{items, total, limit, offset}`, "the shape every other list endpoint already uses", but the existing list endpoints name that key after the resource (`users` in `ListUsersQm`, `organizations` in `ListMyOrganizationsQm`). The checks say "the results"; read whichever key the implementation picks.
- **Whether the email domain is its own search word** (check 5 relies on `xmen` matching `ororo.munroe@xmen.org`). Step 2's tokenization spike decides this.

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`.
2. Start from a fresh, freshly seeded database. `db_pg` has no named volume, so `make down` discards the old database:
   ```shell
   make down
   make upd
   ```
   Searching changes nothing, so no check below needs a reset. If you ran another plan's checks first (they accept invitations and rename organizations), run these two commands again.
3. Each user gets their own cookie file in `/tmp` (for example `/tmp/miles-morales.cookies`). Every check starts by logging in each user it acts as, because a session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN` in `src/app/main/config/settings.py`); an expired cookie gets `401`. A login answers `200` with the user's profile. Each check runs its own read-only **Prove** command before the command under test. Run every command in the same terminal, top to bottom.
4. The accounts (from `SEED_USERS` and `SEED_MEMBERSHIPS` in `scripts/seed_db.py`):
   - `miles-morales` (`WebSlingerHero1!`): platform ADMIN; in no organization.
   - `peter-parker` (`SpideySense2024!`): platform USER; accepted member of all four seeded organizations (OWNER of the Daily Bugle).
   - `bruce-wayne` (`IAmTheNight2024!!`): only a **pending** Avengers invitation.
   - `diana-prince` (`AmazonWarrior$99`): only an **expired** Avengers invitation.
   - `wade-wilson` (`MaximumEffort2024!!!`): in no organization.
   - The organizations: Avengers (`a0000000-0000-4000-8000-000000000001`), X-Men (`a0000000-0000-4000-8000-000000000002`), Defenders (`a0000000-0000-4000-8000-000000000003`), Daily Bugle (`a0000000-0000-4000-8000-000000000004`).

### User search (platform admin only)

1. **Not logged in: 401.**

   **Why:** search needs a logged-in user. This command sends no cookie (there's no `-b`), so the server stops before it looks at `q`.

   **Acts on:** no one: without a cookie there is no caller.
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' 'http://localhost:8000/api/v1/search/users/?q=ton'
   ```
   Expect `401`.

2. **A plain user can't search accounts: 403.**

   **Why:** searching every account, especially by email, is an admin capability, with the same rule as `ListUsers` (`CanManageRole`, target role USER). 403, not 401: peter is logged in, his role is just too low.

   **Acts on:** every account (the user search has no scope).

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** he's a plain USER:
   ```shell
   curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/account/profile/ | python3 -m json.tool
   ```
   Expect `"role": "user"`. Then, as `peter-parker`, search:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/search/users/?q=ton'
   ```
   Expect `403`.

3. **Prefix search finds a user from its first letters: 200.**

   **Why:** search-as-you-type: every word of `q` matches as "starts with", so `ton` finds `tony-stark` before the name is finished. Results are paginated like every other list.

   **Acts on:** every account.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`, with `"role": "admin"`, the **proof** he may search. Then, as `miles-morales`, search `ton`:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=ton&limit=10&offset=0' | python3 -m json.tool
   ```
   Expect `tony-stark` in the results, with the same fields `ListUsers` shows, and `total`, `"limit": 10` and `"offset": 0`.

4. **Every word is a prefix, in any order: 200.**

   **Why:** the query is split into words and each must match as a prefix, in any order, so `par pet` finds `peter-parker`. Ranking puts the best match first.

   **Acts on:** every account.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`, with `"role": "admin"`. Then, as `miles-morales`, search `par pet`:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=par%20pet' | python3 -m json.tool
   ```
   Expect `peter-parker` as the first result.

5. **Keyword search by email: 200.**

   **Why:** users are searchable by email as well as username. A whole word is simply a prefix that happens to be complete, so keyword search needs no separate mode. Depends on Step 2's spike making the email domain a word of its own.

   **Acts on:** every account; the three with an `@xmen.org` email.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`. **Prove** exactly three accounts have an `@xmen.org` email, from the users list:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
     | python3 -c 'import sys, json; [print(u["username"], u["email"]) for u in json.load(sys.stdin)["users"] if u["email"].endswith("@xmen.org")]'
   ```
   Expect `ororo-munroe`, `jean-grey` and `charles-xavier`, and no one else. Then, as `miles-morales`, search `xmen`:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=xmen' | python3 -m json.tool
   ```
   Expect those three in the results, and `"total": 3`.

6. **Pagination is stable across pages: 200.**

   **Why:** results are ordered by relevance, then by `id` as a tie-breaker, so equal-ranked rows never swap between requests. Without it, a row could appear on two pages, or on none.

   **Acts on:** every account; the three `@xmen.org` ones.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`. Then, as `miles-morales`, fetch both pages of `xmen`, two at a time:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=xmen&limit=2&offset=0' | python3 -m json.tool
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=xmen&limit=2&offset=2' | python3 -m json.tool
   ```
   Expect 2 results on the first page and 1 on the second, `"total": 3` on both, and no user on both pages. Fetch both pages again:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=xmen&limit=2&offset=0' | python3 -m json.tool
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=xmen&limit=2&offset=2' | python3 -m json.tool
   ```
   Expect exactly the same users, in the same order.

7. **No match is an empty page, not an error: 200.**

   **Why:** finding nothing is a normal answer to a search, not a failure, so it's `200` with an empty page rather than `404`.

   **Acts on:** every account.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`. **Prove** no username or email contains `zzzz`:
   ```shell
   curl -s -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/users/?limit=50' \
     | python3 -c 'import sys, json; print(sum("zzzz" in u["username"] + u["email"] for u in json.load(sys.stdin)["users"]))'
   ```
   Expect `0`. Then, as `miles-morales`, search `zzzz`:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=zzzz'
   ```
   Expect `200`, with empty results and `"total": 0`.

8. **A 1-character query is too short: 400.**

   **Why:** `SearchQuery` needs at least 2 characters after trimming, because a 1-letter prefix matches almost everything and is expensive. Spaces are trimmed first, so ` t ` counts as 1. It's 400 (a domain rule, `BusinessTypeError`), not 422: `q` is present and is a string.

   **Acts on:** every account.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`, with `"role": "admin"`, so a refusal below can't be about his role. Then, as `miles-morales`, search ` t `:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/?q=%20t%20'
   ```
   Expect `400`.

9. **A query over 100 characters is too long: 400.**

   **Why:** `SearchQuery` caps `q` at 100 characters, so no one can send a huge query to the database. 400 for the same reason as check 8.

   **Acts on:** every account.

   Log in as `miles-morales`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
   ```
   Expect `200`, with `"role": "admin"`. Then, as `miles-morales`, search 101 `a`s:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies -G http://localhost:8000/api/v1/search/users/ \
     --data-urlencode "q=$(printf 'a%.0s' $(seq 1 101))"
   ```
   Expect `400`.

10. **A missing `q`: 422.**

    **Why:** `q` is required, so a request without it is malformed. FastAPI rejects it before any of our code runs: 422, not the 400 a too-short `q` gets.

    **Acts on:** every account.

    Log in as `miles-morales`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
    ```
    Expect `200`. Then, as `miles-morales`, search with no `q`:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/users/'
    ```
    Expect `422`.

### Organization search (scoped to the caller's own organizations)

11. **A member finds their organization by prefix: 200.**

    **Why:** organization search covers only the caller's own accepted memberships, the same scope as `ListMyOrganizations`. peter is in all four, and only one name starts with `ave`.

    **Acts on:** peter-parker's organizations; the match is the Avengers (`a0000000-0000-4000-8000-000000000001`).

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. **Prove** his organizations:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"total": 4`: Avengers, X-Men and Defenders as `member`, Daily Bugle as `owner`. Then, as `peter-parker`, search `ave`:
    ```shell
    curl -s -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/search/organizations/?q=ave&limit=10&offset=0' | python3 -m json.tool
    ```
    Expect only the Avengers (`a0000000-0000-4000-8000-000000000001`) in the results, and `"total": 1`.

12. **Multi-word prefix on an organization name: 200.**

    **Why:** every word is a prefix, so `da bu` finds `Daily Bugle`; a name of several words needs no exact spelling.

    **Acts on:** peter-parker's organizations; the match is the Daily Bugle (`a0000000-0000-4000-8000-000000000004`).

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. **Prove** he belongs to the Daily Bugle:
    ```shell
    curl -s -b /tmp/peter-parker.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"id": "a0000000-0000-4000-8000-000000000004"`, `"name": "Daily Bugle"`, `"role": "owner"`. Then, as `peter-parker`, search `da bu`:
    ```shell
    curl -s -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/search/organizations/?q=da%20bu' | python3 -m json.tool
    ```
    Expect the Daily Bugle in the results.

13. **An outsider sees nothing, not an error: 200 with an empty page.**

    **Why:** there is no global organization directory; a search must never reveal an organization to a non-member. An empty page, not 403 or 404, because the search itself is allowed: it just has nothing of wade's to find.

    **Acts on:** wade-wilson's organizations (none); the Avengers (`a0000000-0000-4000-8000-000000000001`) is the name he tries.

    Log in as `wade-wilson`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
    ```
    Expect `200`. **Prove** wade belongs to no organization:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"organizations": []` and `"total": 0`. Then, as `wade-wilson`, search `ave`:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies 'http://localhost:8000/api/v1/search/organizations/?q=ave'
    ```
    Expect `200`, with empty results and `"total": 0`.

14. **A pending invitation's organization never appears: 200 with an empty page.**

    **Why:** an invitation isn't a membership until it's accepted. Until then bruce is an outsider, exactly as in `ListMyOrganizations`.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and bruce's pending invitation to it (`b0000000-0000-4000-8000-000000000001`).

    Log in as `bruce-wayne`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/bruce-wayne.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "bruce-wayne", "password": "IAmTheNight2024!!"}'
    ```
    Expect `200`. **Prove** he has a pending Avengers invitation and no membership:
    ```shell
    curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/invitations/ | python3 -m json.tool
    curl -s -b /tmp/bruce-wayne.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"membership_id": "b0000000-0000-4000-8000-000000000001"` with `"organization_name": "Avengers"`, then `"total": 0`. Then, as `bruce-wayne`, search `ave`:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/bruce-wayne.cookies 'http://localhost:8000/api/v1/search/organizations/?q=ave'
    ```
    Expect `200`, with empty results and `"total": 0`.

15. **An expired invitation's organization never appears: 200 with an empty page.**

    **Why:** the same rule as check 14: an expired invitation was never accepted, so diana is not a member.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`), and diana's expired invitation to it (`b0000000-0000-4000-8000-000000000002`).

    Log in as `diana-prince`, and as `peter-parker`, who does the proving:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/diana-prince.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "diana-prince", "password": "AmazonWarrior$99"}'
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200` both times. **Prove** diana's invitation exists but has expired, by listing the Avengers' members as `peter-parker`, then that diana has no membership:
    ```shell
    curl -s -b /tmp/peter-parker.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    curl -s -b /tmp/diana-prince.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect a `diana-prince` row with `"membership_id": "b0000000-0000-4000-8000-000000000002"`, `"accepted_at": null` and an `expires_at` in the past, then `"total": 0`. Then, as `diana-prince`, search `ave`:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/diana-prince.cookies 'http://localhost:8000/api/v1/search/organizations/?q=ave'
    ```
    Expect `200`, with empty results and `"total": 0`.

16. **A platform admin gets no global organization directory: 200 with an empty page.**

    **Why:** a platform role gives no access to organizations; they are private tenants. miles is an ADMIN but belongs to none, so his search finds none.

    **Acts on:** miles-morales's organizations (none); the Avengers (`a0000000-0000-4000-8000-000000000001`) is the name he tries.

    Log in as `miles-morales`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/miles-morales.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "miles-morales", "password": "WebSlingerHero1!"}'
    ```
    Expect `200`, with `"role": "admin"`. **Prove** he belongs to no organization:
    ```shell
    curl -s -b /tmp/miles-morales.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"organizations": []` and `"total": 0`. Then, as `miles-morales`, search `ave`:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/miles-morales.cookies 'http://localhost:8000/api/v1/search/organizations/?q=ave'
    ```
    Expect `200`, with empty results and `"total": 0`.

17. **The same `q` rules apply to organization search: 400, then 422.**

    **Why:** both searches use the one `SearchQuery` value object, so a 1-character `q` is 400 (a domain rule) and a missing `q` is 422 (a malformed request) here too.

    **Acts on:** peter-parker's organizations.

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. Then, as `peter-parker`, search `a`, then with no `q`:
    ```shell
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/search/organizations/?q=a'
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/peter-parker.cookies 'http://localhost:8000/api/v1/search/organizations/'
    ```
    Expect `400`, then `422`.
