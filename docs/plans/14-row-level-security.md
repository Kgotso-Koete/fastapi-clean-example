# 14. Postgres Row-Level Security for organization-owned tables

> **Status: planned, not started. Decided to go ahead** (human maintainer, 2026-10-02): full RLS as designed below, rather than the cheaper alternative of a test-time check for unfiltered organization queries. Invitation acceptance uses Decision 6(a). Sequenced after profile editing (`docs/plans/10-profile-editing.md`) and before search and file storage (`docs/plans/11-search.md`, `docs/plans/12-file-storage.md`), which both add queries over organization data. It builds on the RLS spike in `docs/plans/9-organizations.md` Step 9 (`tests/integration/with_infra/organizations/test_rls_spike.py`), and must cover everything plan 9's close-out adds (delete and edit organization). **No new dependencies:** plain SQL in Alembic migrations plus a SQLAlchemy event listener, on the existing stack (web process + Postgres). **OWASP is the primary authority** (`docs/plans/agents.md` 6.2).

## Goal

A second, database-level layer of tenant isolation under the application-layer checks (`CurrentOrganizationService`/`CanAccessOrganization`), so that a query that forgets its `WHERE organization_id = ...` returns no rows instead of another organization's data. The application-layer check stays the first layer; RLS is defence in depth.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Contained mistakes | maintainer of a fork | a forgotten organization filter to return nothing | one bug can't leak one customer's data to another | With no organization bound, an unfiltered `SELECT` on an organization-owned table returns 0 rows<br>It fails closed on both fresh and reused pooled connections, never with an error<br>A garbage (non-UUID) context raises, never returns rows |
| 2. Everything still works | organization member | every organization feature to keep working under RLS | isolation doesn't break the product | My organization and invitation lists return exactly my rows, across organizations<br>Member counts stay correct<br>Creating, accepting, declining, editing and deleting all still work |
| 3. No cross-organization writes | maintainer | a write into another organization to be refused by the database | a bug can't plant or change rows in someone else's organization | A cross-organization `INSERT`, or an `UPDATE` moving a row to another organization, fails with SQLSTATE 42501<br>A cross-organization `UPDATE`/`DELETE` affects 0 rows, and the row is unchanged |
| 4. Unprivileged app | maintainer | the web app to connect as a role that can't bypass RLS | the policies actually apply | The web and public-API connections are neither superuser nor `BYPASSRLS` and own no tables<br>The app checks this at startup, in every environment |
| 5. Visible attempts | maintainer | denied cross-organization attempts to be logged with who and what | probing or a broken check is noticed | A non-member's or under-privileged request logs a WARNING with the user id and requested organization id<br>A database-level isolation violation logs an ERROR with context, triggers the existing alert, and leaks no SQL to the client |

## What the research found

### OWASP, the primary authority

The OWASP Multi-Tenant Security Cheat Sheet (https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html) was checked recommendation by recommendation against this plan and the existing code. The related Authorization and Logging cheat sheets were checked too (https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html, https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

- **Already met by the existing app:**
  - organization ids from the client are selectors only, verified against an accepted membership, with 404 for non-members;
  - lookups are scoped by organization;
  - opaque UUIDs are never treated as authorization;
  - authorization is checked in every use case.
- **Met by this plan:**
  - a separate request role that can't bypass RLS;
  - transaction-local context, re-established for every transaction;
  - failing closed;
  - testing connection reuse across two organizations.
- **Gaps this plan now closes:**
  - check the *deployed* request role, not only in tests (startup self-check);
  - a full allow-and-deny matrix for every operation, not just `SELECT` and `INSERT`;
  - a coverage gate that classifies *every* table, rather than a column heuristic. A hand-maintained or column-based list drifts: `event_outbox.payload` already holds an organization name and an invitee email, with no `organization_id` column;
  - log denied attempts and isolation failures with server-verified ids;
  - never let the context be silently replaced within a request;
  - privileged jobs must scope their own tenant set, because RLS won't.
- **A conscious deviation from OWASP's *example*, not its requirement:** OWASP's sample policy omits `missing_ok`, so a missing context raises. This plan uses `NULLIF(current_setting(name, true), '')`, so a missing context returns no rows. Both fail closed. Empty results are needed here because the cross-organization queries run with no organization bound.
- **Considered and rejected:** application-level filtering with SQLAlchemy's `do_orm_execute`/`with_loader_criteria`. This codebase mostly uses Core `select(table.c...)`, which that pattern doesn't cover (OWASP says as much), and RLS is the final boundary anyway; the explicit `WHERE` clauses stay.

### Other sources

Read in detail, with trust signals checked on 2026-10-01. Where a source disagrees with OWASP, this plan sides with OWASP.

- PostgreSQL docs: https://www.postgresql.org/docs/current/ddl-rowsecurity.html, https://www.postgresql.org/docs/current/sql-createpolicy.html, https://www.postgresql.org/docs/current/functions-admin.html, https://www.postgresql.org/docs/current/sql-createfunction.html
- Supabase docs and measured performance guidance: https://supabase.com/docs/guides/database/postgres/row-level-security, https://github.com/orgs/supabase/discussions/14576
- PostgREST's role and transaction model: https://docs.postgrest.org/en/stable/references/auth.html, https://docs.postgrest.org/en/stable/references/transactions.html
- AWS blog (2020) and sample (131 stars, 2019 to 2023): https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/, https://github.com/aws-samples/aws-saas-factory-postgresql-rls
- Crunchy Data (2024): https://www.crunchydata.com/blog/row-level-security-for-tenants-in-postgres; Nile (2022): https://www.thenile.dev/blog/multi-tenant-rls
- Teaching material, including the sources the human maintainer supplied:
  - https://github.com/ricofritzsche/multi-tenant-rls-demo and https://ricofritzsche.me/mastering-postgresql-row-level-security-rls-for-rock-solid-multi-tenancy/ (2025);
  - https://github.com/jacobcantwell/multi-tenant-data-isolation-with-postgresql-row-level-security-extension (2020, labelled alpha);
  - https://github.com/simplyblock/example-rls-invoicing (10 stars, 2025, no tests) and its post https://vela.run/blog/row-level-security-postgres/;
  - a Prisma tutorial (https://medium.com/@francolabuschagne90/securing-multi-tenant-applications-using-row-level-security-in-postgresql-with-prisma-orm-4237f4d4bd35, 2024);
  - https://github.com/Telemaco019/sqlalchemy-tenants (4 stars, 2025);
  - practitioner discussion at https://www.reddit.com/r/django/comments/1fwez1p/multi_tenant_framework_with_row_level_security/;
  - https://stackoverflow.com/questions/69986599/what-are-the-best-practices-for-advanced-row-level-security-in-ssas-tabular-mode (Microsoft SSAS, not Postgres; only its design lesson transfers).
- Not readable: the r/PostgreSQL thread (https://www.reddit.com/r/PostgreSQL/comments/1nk4c3a/underrated_postgres_build_multitenancy_with/) blocks automated readers and has no archive copy.

Findings that shape this plan:

1. **The spike's policy has a pooling bug.** After a connection has once set the variable transaction-locally, `current_setting(name, true)` returns `''`, not `NULL`, for the rest of that connection, and `''::uuid` raises. The fix (Crunchy Data, Nile) is `NULLIF(current_setting(name, true), '')::uuid`. The spike only passes because each test uses a fresh connection. Reported on the PostgreSQL list: https://www.postgresql.org/message-id/CA+Q86ij0KDCB0G45G509-8q0DNR611gcKG-sSM83GA1EBL7boA@mail.gmail.com
2. **Superusers ignore even `FORCE ROW LEVEL SECURITY`;** `FORCE` only affects the table owner. The fix for the spike's blocker is a separate login role.
3. **Transaction-local `set_config(name, value, true)` is the safe mechanism** with a connection pool, and the one that also works behind PgBouncer in transaction mode. Session-level `SET` and `SET ROLE` survive into the next checkout. Several samples get this wrong: AWS uses session `SET` built by string concatenation, with errors swallowed; simplyblock uses a superuser login plus session `SET ROLE`, with the tenant taken from unverified request headers.
4. **Never a setting-based bypass.** The Prisma tutorial adds a policy that lets everything through when `app.bypass_rls = 'on'`; any code path or SQL injection that can call `set_config` would then bypass all isolation. Cross-organization access here goes only through narrow `SECURITY DEFINER` functions or the owner role.
5. **One user in several organizations** needs a user-keyed branch in the policy (`... OR user_id = current_user_id`), as Supabase does. Cross-organization aggregates such as the member count need a `SECURITY DEFINER` function: `SET search_path = ''` with every name schema-qualified, `EXECUTE` revoked from `PUBLIC`, and its own check inside.
6. **Performance (Supabase's measurements):**
   - wrap each setting in `(SELECT ...)` so it's evaluated once per statement;
   - write membership checks as `id IN (SELECT organization_id FROM ... WHERE user_id = ...)`, not a per-row correlated `EXISTS` (9 s down to 20 ms in their test);
   - scope policies `TO` the runtime role;
   - keep the explicit `WHERE` filters;
   - index the policy columns. `organization_memberships` has no index led by `user_id` yet.
7. **Keep policies simple** (the SSAS lesson): equality or `IN` checks against indexed membership rows. Future complexity, such as teams or per-resource sharing, goes into membership data, not into policy logic.
8. **`TRUNCATE` and referential-integrity checks aren't subject to RLS.**
   - `TRUNCATE`: the integration-test cleanup fixture truncates through the app's sessionmaker, so cleanup and fixture seeding move to an owner-role connection, and the runtime role never gets `TRUNCATE`.
   - Referential-integrity checks: the `ON DELETE CASCADE` from organizations to memberships still runs under RLS, and removes every member's rows.
   - Unique and foreign-key violations are a known existence side channel. Random UUIDs and 404s keep the risk low, but constraint error text must never reach a client.
9. **No Python RLS library is mature enough to adopt.**
   - `sqlalchemy-tenants` uses one database role per tenant (session-level `SET SESSION ROLE`), needs permission to create roles at runtime, can't model one user in several organizations, and its own tests use `NullPool`, so pooled-connection leaks are never tested.
   - The Django RLS libraries are all from 2025 or later.
   - Practitioners in the r/django thread mostly build their own.
   - `alembic_utils` (301 stars, since 2020) would add autogenerate for policies; the catalog guard test covers the same need without a dependency.

## Design

### Roles

- `postgres` stays the table owner and keeps running migrations.
- A migration creates a no-login group role, `app_runtime` (`NOSUPERUSER NOBYPASSRLS`), with grants listed per table, in the migration that creates or changes each table. There's no `ALTER DEFAULT PRIVILEGES`, so a new table is denied to the app until a migration grants it (OWASP "deny by default"):
  - `SELECT`, `INSERT`, `UPDATE` and `DELETE` on `users`, `auth_sessions`, `api_keys`, `event_outbox`, `organizations` and `organization_memberships`;
  - never `TRUNCATE`;
  - nothing on `alembic_version`;
  - no sequences are needed, since every primary key is a UUID.
- A login role joins that group, with new settings `POSTGRES_APP_USER` and `POSTGRES_APP_PASSWORD`. Only the web app and the public API connect with it.
- **Startup self-check:** when the web and public-API processes start, they query `pg_roles` for `current_user`. They refuse to start if the role is a superuser, has `BYPASSRLS`, or owns any table. That check runs in every environment (OWASP: check the deployed role, not only the configuration).

### Context

- **The settings:** two transaction-local settings, `app.current_user_id` and `app.current_organization_id`, always set with parameterized `set_config(..., true)`.
- **The port:** a new `RowSecurityContext` port with `bind_user` and `bind_organization`. Its adapter does two things:
  1. stores the value in `session.info`, so an `after_begin` listener re-applies it at the start of every later transaction (after a commit);
  2. if a transaction is already open, applies it to that transaction immediately.

  The second part is essential. By the time a use case can bind anything, `CurrentUserService` and `MembershipChecker` have already queried the database, and that query opened the transaction. A design that relies on `after_begin` alone would bind nothing for the rest of the request.
- **Where the context is set:** in each use case, through `require_role()`, not in middleware. The organization id comes from the path and is only trustworthy once the membership lookup has verified it. The user is bound where `CurrentUserService` resolves the caller.
- **What may be bound:** the organization is bound only with the id `require_role()` verified, never with a raw request value. `CreateOrganization` binds the id it generates server-side, before staging its inserts.
- **No silent replacement:** binding a *different* organization within the same request raises an error (OWASP: the verified context mustn't be replaced downstream).
- **A forgotten bind** gives empty results, never another organization's rows.

### Policies

Every policy is scoped `TO app_runtime`, with each setting wrapped as `(SELECT NULLIF(current_setting('app.current_...', true), '')::uuid)`.

- **`organization_memberships`:**
  - read and delete when `organization_id = current_organization OR user_id = current_user`;
  - insert and update only for the current organization (`WITH CHECK`);
  - this policy never references `organizations`, which avoids recursive policies (42P17).
- **`organizations`:**
  - visible when it's the current organization, or `id IN (SELECT organization_id FROM organization_memberships WHERE user_id = current_user)`. That includes a *pending* invitee, so `ListMyInvitations` can show the organization's name, while `MembershipChecker` still treats them as a non-member, because `accepted_at` is `NULL`;
  - insert with `WITH CHECK (id = current_organization AND created_by_user_id = current_user)`;
  - update and delete only for the current organization.
- **`SECURITY DEFINER` functions,** each with `SET search_path = ''`, schema-qualified names, `EXECUTE` revoked from `PUBLIC` and granted only to `app_runtime`:
  - the member count, used by `SqlaOrganizationReader.list_for_user`;
  - `accept_invitation(membership_id)`, if Decision 6(a) is chosen.
- **An index** on `organization_memberships.user_id`.
- **No setting-based bypass policy, ever.**
- **Views:** any future view over an organization-owned table is created `WITH (security_invoker = true)`. Postgres 18 is in use, so this is supported.

### Existing files this touches (flagged, per `agents.md` 3.1)

- `src/app/main/ioc/outbound.py`: one argument, to attach the listener to the sessions.
- Settings and loader: the runtime-role settings, each with its own env-var test in `test_loader.py` (`agents.md` 2.3).
- The web and public-API startup: the role self-check.
- `src/app/core/common/authorization/current_organization_service.py`: binding the verified organization, and WARNING logs with the user id and requested organization id on a 404 or 403.
- `src/app/core/commands/create_organization.py`: bind the new organization's id.
- `src/app/core/commands/accept_organization_invitation.py` (or its repository): the accept path, per Decision 6.
- `src/app/outbound/adapters/sqla_organization_reader.py`: the member-count function call.
- The error path for SQLSTATE 42501: logged at ERROR with context and alerted, not swallowed as a generic 503, with no SQL in the response.
- `tests/integration/with_infra/conftest.py`: cleanup and seeding through an owner-role engine.
- `env.example`, `docker-compose.yml` (with `${VAR:-default}` fallbacks, `agents.md` 5.4), and an init-script mount for the dev and test role.

## Decisions for the human maintainer

1. **Where the login role is created:**
   - **(a) Recommended:** a Postgres init script for dev and test (run only on a fresh volume), and ops in production. No password enters migration history.
   - **(b)** In a migration, which puts a password in migration history.
2. **`FORCE ROW LEVEL SECURITY`:** recommended on, as cheap belt and braces in case the app ever connects as the owner.
3. **Worker, CLI and seed script stay privileged** (connecting as `postgres`): recommended, as a documented decision. OWASP adds that a privileged job must constrain its own tenant set, because RLS won't. Today that holds: the only worker handler reads no organization tables. Any future worker handler or CLI command that reads organization-owned tables must either take an explicit organization id and filter on it, or connect as the runtime role and bind the context.
4. **Database-level guard against a member editing their own role:** today only the application layer prevents it. Recommended: not in this plan.
5. **The spike test:** recommended to keep it until Step 3 replaces it, then retire it.
6. **How accepting an invitation works under RLS.** The invitee isn't an accepted member yet, so no organization is bound, and an `UPDATE` policy limited to the current organization would match 0 rows. SQLAlchemy then raises a stale-data error, and the user would get a 500. A plain "update your own row" policy would let a member promote themselves at the database level, because RLS can't compare old and new values.
   - **What established codebases do.** Every RLS-based SaaS codebase researched routes the invitee's write through a narrow privileged function. None gives the invitee a "you may update your own membership rows" policy.
     - Basejump: 940 stars, since 2022; `accept_invitation()` in `supabase/migrations/20240414162100_basejump-invitations.sql`. Its membership table has no `INSERT` or `UPDATE` policy at all. https://github.com/usebasejump/basejump
     - supabase-tenant-rbac: 476 stars, since 2023; its `accept_invite` is documented as "bootstrap: atomically adds membership without prior RLS", which is exactly this problem. https://github.com/point-source/supabase-tenant-rbac
     - MakerKit uses a separate invitations table, accepted through a privileged server-side path: https://makerkit.dev/docs/next-supabase-turbo/development/database-architecture
     - The non-RLS projects (apptension/saas-boilerplate, cal.com, Documenso, Twenty) enforce acceptance in the application layer only.
   - **Decided: (a)**, by the human maintainer, 2026-10-02.
   - **(a) (the Basejump and supabase-tenant-rbac pattern):** `accept_invitation(p_membership_id uuid)`:
     1. `SECURITY DEFINER`, owned by the table owner, with `SET search_path = ''` and schema-qualified names, `EXECUTE` revoked from `PUBLIC` and granted only to `app_runtime`.
     2. It takes **no user-id argument**. The caller is the transaction-local `NULLIF(current_setting('app.current_user_id', true), '')::uuid`, and with no bound user it changes nothing.
     3. A single atomic statement: `UPDATE ... SET accepted_at = now(), expires_at = NULL WHERE id = p_membership_id AND user_id = <current user> AND accepted_at IS NULL AND (expires_at IS NULL OR expires_at > now()) RETURNING id`. It never touches `role` or `organization_id`, and there's no read-then-write race.
     4. It returns the id, or `NULL`. The domain checks (`membership.accept()`, `is_expired()`) still run first and give the existing 404 or 410; the function is the final gate.
     5. A dedicated repository port method calls it, instead of letting the ORM flush an `UPDATE`, so the change stays additive.
     6. Open: whether `accepted_at` comes from the database's `now()` or the app's `UtcTimer`. Either is fine, as long as the expiry check stays in the `WHERE`.

     A caveat: the function relies on its owner bypassing RLS. If the table owner were ever a non-superuser with `FORCE` on (Decision 2), the function would be filtered too, so Step 4's tests must run it the way production does.
   - **(b) Rejected:** a user-keyed `UPDATE` policy plus column-level `GRANT UPDATE (accepted_at, expires_at)`.
     - Column privileges belong to a role, not to a policy. `app_runtime` needs `UPDATE (role)` for `ChangeOrganizationMemberRole`, so this either breaks admin role changes or lets a member promote themselves.
     - A writable `expires_at` would let an invitee revive an expired invitation, and a writable `accepted_at` would let them un-accept a row.
     - Supabase advises against column privileges for most users: https://supabase.com/docs/guides/database/postgres/column-level-security
   - **(c) Rejected:** a user-keyed policy plus a `BEFORE UPDATE` trigger comparing `OLD` and `NEW`. It works, but it puts "which caller is this" logic into a trigger, against this plan's "keep policies simple", and no trusted project accepts invitations this way. Triggers like this are used for column protection on tables the client may legitimately update (Basejump's `protect_account_fields`), which makes one a reasonable optional guard for Decision 4, not for Decision 6.
   - **(d) Not adopted:** a separate invitations table with a token (MakerKit, Documenso, Twenty, Nile). It's cleaner in the abstract, but it's a non-additive remodel of plan 9's data, and accepting would still need (a) to insert the membership. Revisit only if invitations are ever redesigned.
7. **Organization routes on the public API under RLS.** OWASP says API credentials should be bound to an explicit set of tenants. Today's API keys are user-scoped, so they implicitly span every organization the user belongs to. That matters for `docs/plans/9-organizations.md` Step 15, the two read-only organization queries on the public API:
   - **(a)** Keep Step 15 as decided, with user-scoped keys. Under RLS, the public API binds the key's user, and the reads stay limited to that user's own memberships.
   - **(b) OWASP-aligned:** give API keys an explicit organization scope first (the roadmap's scoped-API-keys item), then expose organization routes. This is consistent with OWASP's rule.
   - **Decided: (a)**, by the human maintainer, 2026-10-02. This knowingly departs from OWASP's rule, and the reason is recorded here. The two routes are read-only, and they go through the same membership checks as the cookie routes, so a key never sees more than its owner already can. Organization *writes* on the public API still wait for scoped API keys (see Follow-ups).

## Proposed changes (each step: test first, confirmed RED, then code, confirmed GREEN)

1. **The runtime role exists and is unprivileged.**
   - Test: connect with the new credentials, and assert the role isn't a superuser, has no `BYPASSRLS`, owns no tables and is a member of `app_runtime`. RED: authentication fails.
   - Code: the migration creating `app_runtime` with its per-table grants, the init script and env vars, and the new loader (its `test_loader.py` test first).
2. **Classification-based catalog guard.**
   - Test: every table in the database is listed in an explicit classification: organization-scoped, user-scoped, global, or system (such as `alembic_version`). An unclassified table fails the test.
   - Test: every organization-scoped table has RLS, `FORCE` (if chosen) and at least one policy; every table with an `organization_id` column is classified organization-scoped.
   - Test: `app_runtime` has no `TRUNCATE` anywhere and no grants outside the classification, and no view reading an organization-scoped table lacks `security_invoker`.
   - Code: the RLS migration with its policies, the `user_id` index and downgrade steps.
3. **The isolation matrix at the SQL level, through the runtime role,** for both tables:
   - an unfiltered `SELECT` returns only the bound organization's rows;
   - nothing on a fresh connection, and nothing with no error on a reused pooled connection. This is a genuine RED without `NULLIF`;
   - a garbage context raises;
   - same-organization `INSERT`, `UPDATE` and `DELETE` succeed, proven with `RETURNING` (never "no error", which also passes when nothing matched);
   - cross-organization `UPDATE` and `DELETE` affect 0 rows, and an owner-role read shows the row unchanged;
   - a cross-organization `INSERT`, or an `UPDATE` moving a row to another organization, fails with 42501;
   - the user branch returns exactly the user's own rows across organizations;
   - a pending invitee can read the organization's row;
   - the `ON DELETE CASCADE` removes every member's rows.
4. **The `SECURITY DEFINER` functions.**
   - Member count: a member gets the count, a non-member gets `NULL`, and `PUBLIC` has no `EXECUTE`.
   - If Decision 6(a) is chosen, `accept_invitation`:
     - the caller's own pending row is accepted;
     - someone else's row, an already-accepted row and an expired row are each refused;
     - a call with no bound user changes 0 rows;
     - afterwards, an owner-role read shows `role` and `organization_id` unchanged.
5. **The `RowSecurityContext` port and adapter.**
   - Test: a bind made after a query has already opened the transaction is visible in that same transaction. That's a genuine RED against an `after_begin`-only design.
   - Test: the bind is re-applied after a commit; a fresh session sees none; re-binding a different organization raises.
   - RED: an import error, with the port introduced in this same cycle.
   - Code: the adapter, the `after_begin` listener and the flagged `outbound.py` change.
6. **Pool hygiene.** Test, through the app's real engine and pool configuration (not `NullPool`): two sequential requests on one pooled connection don't see each other's context. SQLAlchemy's rollback on return is the mechanism under test. If it passes straight away, it's recorded honestly as a confirmation test, not a RED-driven step.
7. **Bind the context in the request path.**
   - Tests: HTTP regressions for every organizations route with the app running as the runtime role, including create, invite, accept, decline, remove, change role, edit and delete, and the public-API routes. RED: empty lists, 404s and 500s.
   - Tests: a denied attempt logs a WARNING with the user and organization ids; a forced 42501 logs an ERROR with context, reaches the alert path, and puts no SQL in the response.
   - Code:
     - bind the user where it's resolved, and the organization after `CanAccessOrganization`;
     - `CreateOrganization` binds its new id;
     - accept goes through Decision 6;
     - switch `list_for_user` to the member-count function;
     - the logging, and the 42501 error path;
     - move test cleanup and seeding to the owner engine.
8. **The startup self-check.** Test: starting with a superuser, a `BYPASSRLS` role or a table-owning role refuses to start; starting with the runtime role succeeds. Code: the check in the web and public-API startup.
9. **Pin each entrypoint's role.** Tests: the worker and CLI connect as `POSTGRES_USER`; the web app and public API connect as the runtime role.
10. **Docs and human checks:**
    - curl as two users against each route;
    - `psql` as the runtime role: with no context, `SELECT` returns 0 rows; inside `BEGIN`/`set_config`/`COMMIT`, only that organization's rows; a cross-organization `INSERT` fails;
    - `EXPLAIN ANALYZE` of the policy queries as the runtime role;
    - the same role query the startup check runs, against production;
    - a PgBouncer note: transaction-local settings work in transaction pooling mode, session settings don't;
    - backups and restores run as the owner and are cross-tenant by nature, so restoring a single organization means restoring into a separate database and copying that organization's rows;
    - the wiki, the `CHANGELOG.md` entry and version, and the roadmap and README checklist.

## Follow-ups and non-goals

Out of scope here, recorded so they aren't lost (OWASP sections in brackets):
- When rate limiting lands (roadmap P0), add an organization dimension for organization routes, starting with invitation sending, so one organization can't spam invitations (5).
- When caching lands, cache keys for organization data include the organization id, authorization runs before a cache read, and shared entries live in an explicit global namespace (4).
- Before any organization *write* reaches the public API, API keys need an explicit organization scope (5); see Decision 7 for reads.
- The invitation email handler re-checks, before sending, that the invitation is still pending, so a revoked invitation isn't emailed (5, stale permission decisions).
- Pseudonymize the invitee's email in the invitation handler's logs, for example log the membership id instead (8).
- A retention, deletion and audit policy for deleted organizations (7).
- File storage (`docs/plans/12-file-storage.md`) uses organization-scoped object keys, authorizes before signing any URL, and validates key structure (6).
- Per-organization encryption keys, and an audit-log retention and access policy: non-goals for now (7, 8).

## Verification plan

- `make check` at every GREEN; `make test-docker` after every database or wiring step.
- Human checks, written into this plan as each step lands, in the `docs/plans/agents.md` 1.3 format.
