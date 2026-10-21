# 14. Postgres Row-Level Security for organization-owned tables

> **Status: in progress** (2026-10-21): Steps 1 and 2 built, Step 3 under way, all uncommitted. **Scope narrowed and reordered** (human maintainer, 2026-10-21): this plan now covers customer isolation only (Steps 1 to 9, and 15); staff access (Steps 10 to 14) becomes its own plan, and the remaining work follows "Order of work" under Proposed changes, which takes one use case through every layer first. **Decided to go ahead** (human maintainer, 2026-10-02): full RLS as designed below, rather than the cheaper alternative of a test-time check for unfiltered organization queries. Invitation acceptance uses Decision 6(a). Sequenced after profile editing (`docs/plans/10-profile-editing.md`) and before search and file storage (`docs/plans/11-search.md`, `docs/plans/12-file-storage.md`), which both add queries over organization data. It builds on the RLS spike in `docs/plans/9-organizations.md` Step 9 (`tests/integration/with_infra/organizations/test_rls_spike.py`), and must cover everything plan 9's close-out adds (delete and edit organization). **No new dependencies:** plain SQL in Alembic migrations plus a SQLAlchemy event listener, on the existing stack (web process + Postgres). **OWASP is the primary authority** (`docs/plans/agents.md` 6.2). **Scope extended** (human maintainer, 2026-10-14): cross-organization access for platform staff, both read-only and narrow audited writes, is part of this plan, so organization RLS closes out here. **Complexity re-checked** (human maintainer, 2026-10-14): this full design (A) was compared with staff access through the customer policies (B) and no RLS at all (C), and kept.

## Goal

A second, database-level layer of tenant isolation under the application-layer checks (`CurrentOrganizationService`/`CanAccessOrganization`), so that a query that forgets its `WHERE organization_id = ...` returns no rows instead of another organization's data. The application-layer check stays the first layer; RLS is defence in depth.

Platform staff who operate the service, such as support, sometimes need to see every organization's data, and some need to correct specific fields in any organization. That access goes through its own explicit, separately authorized and audited path (OWASP: cross-tenant access "requires an explicit platform permission"), never through a bypass of the customer-facing rules.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Contained mistakes | maintainer of a fork | a forgotten organization filter to return nothing | one bug can't leak one customer's data to another | With no organization bound, an unfiltered `SELECT` on an organization-owned table returns 0 rows<br>It fails closed on both fresh and reused pooled connections, never with an error<br>A garbage (non-UUID) context raises, never returns rows |
| 2. Everything still works | organization member | every organization feature to keep working under RLS | isolation doesn't break the product | My organization and invitation lists return exactly my rows, across organizations<br>Member counts stay correct<br>Creating, accepting, declining, editing and deleting all still work |
| 3. No cross-organization writes | maintainer | a write into another organization to be refused by the database | a bug can't plant or change rows in someone else's organization | A cross-organization `INSERT`, or an `UPDATE` moving a row to another organization, fails with SQLSTATE 42501<br>A cross-organization `UPDATE`/`DELETE` affects 0 rows, and the row is unchanged |
| 4. Unprivileged app | maintainer | the web app to connect as a role that can't bypass RLS | the policies actually apply | The web and public-API connections are neither superuser nor `BYPASSRLS` and own no tables<br>The app checks this at startup, in every environment |
| 5. Visible attempts | maintainer | denied cross-organization attempts to be logged with who and what | probing or a broken check is noticed | A non-member's or under-privileged request logs a WARNING with the user id and requested organization id<br>A database-level isolation violation logs an ERROR with context, triggers the existing alert, and leaks no SQL to the client |
| 6. Cross-organization reading | platform staff member with read access | to see every organization's records, filtered as I need | I can support customers and operate the service | I see rows from every organization, and my filters (dates, names) work as usual<br>Any write through the read path fails with SQLSTATE 42501<br>I can't read secrets such as password hashes<br>A user without staff read access is refused<br>Each cross-organization read is logged with who asked and what for |
| 7. Cross-organization corrections | platform staff member with write access | to correct specific fields on any organization's records, with a reason | a customer's problem can be fixed without database access | Only the fields granted to staff can change; any other field, and moving a row to another organization, fails with 42501<br>Inserts and deletes across organizations fail<br>A correction without a reason is refused<br>Each correction is logged with who made it, which organization and record, and the reason (an audit table was taken out of scope on 2026-10-21; see the roadmap)<br>A staff member with only read access can't correct anything |

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

**Local copies, for re-reading** (all re-read on 2026-10-15). Every source below has a saved copy in `ai_research/14-row-level-security/` at the repository root (each plan's research has its own folder, named after the plan). So do the three OWASP cheat sheets, PostgreSQL's privileges and privilege-function pages (https://www.postgresql.org/docs/current/ddl-priv.html, https://www.postgresql.org/docs/current/functions-info.html) and its GRANT page (https://www.postgresql.org/docs/current/sql-grant.html).
- `ai_research/14-row-level-security/repos/`: the cloned sample repositories.
- `ai_research/14-row-level-security/web/`: the raw downloads.
- `ai_research/14-row-level-security/text/`: a plain-text copy of each page, made with `ai_research/tools/to_text.py`.

The folder is git-ignored, so it exists only on the machine that downloaded it. An AI agent resuming this plan re-reads it instead of fetching the web again. If it's missing, rebuild it from the URLs in this section. The two Reddit threads come from the Arctic Shift archive (for example https://arctic-shift.photon-reddit.com/api/posts/ids?ids=1fwez1p, and `comments/search?link_id=1fwez1p` for its comments), because Reddit blocks automated readers.

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
- The r/PostgreSQL thread (https://www.reddit.com/r/PostgreSQL/comments/1nk4c3a/underrated_postgres_build_multitenancy_with/), read on 2026-10-15 through the Arctic Shift archive: the post announcing the simplyblock example, with comments on connection pooling and PgBouncer. Nothing in it changes this design.

Findings that shape this plan:

1. **The spike's policy has a pooling bug.** After a connection has once set the variable transaction-locally, whether that transaction commits or rolls back, `current_setting(name, true)` returns `''`, not `NULL`, for the rest of that connection, and `''::uuid` raises. The fix (Crunchy Data, Nile) is `NULLIF(current_setting(name, true), '')::uuid`. The spike only passes because each test uses a fresh connection. PostgREST's transactions reference documents the same behavior and the same `nullif` fix. Reported on the PostgreSQL list (2018, reproduced with a rollback): https://www.postgresql.org/message-id/CA+Q86ij0KDCB0G45G509-8q0DNR611gcKG-sSM83GA1EBL7boA@mail.gmail.com
2. **Superusers ignore even `FORCE ROW LEVEL SECURITY`;** `FORCE` only affects the table owner. The fix for the spike's blocker is a separate login role.
3. **Transaction-local `set_config(name, value, true)` is the safe mechanism** with a connection pool, and the one that also works behind PgBouncer in transaction mode. Session-level `SET` and `SET ROLE` survive into the next checkout. Several samples get this wrong: AWS uses session `SET` built by string concatenation, with errors swallowed; simplyblock uses a superuser login plus session `SET ROLE`, with the tenant taken from unverified request headers.
4. **Never a setting-based bypass.** The Prisma tutorial adds a policy that lets everything through when `app.bypass_rls = 'on'`; any code path or SQL injection that can call `set_config` would then bypass all isolation. Cross-organization access here goes only through narrow `SECURITY DEFINER` functions or the owner role.
5. **One user in several organizations** needs a user-keyed branch in the policy (`... OR user_id = current_user_id`), as Supabase does. Cross-organization aggregates such as the member count need a `SECURITY DEFINER` function: `SET search_path = ''` with every name schema-qualified, `EXECUTE` revoked from `PUBLIC`, and its own check inside.
6. **Performance (Supabase's measurements):**
   - wrap each setting in `(SELECT ...)` so it's evaluated once per statement;
   - write membership checks as `id IN (SELECT organization_id FROM ... WHERE user_id = ...)`, not a correlated subquery that runs once per row (9,000 ms down to 20 ms in their test);
   - scope policies `TO` the runtime role;
   - keep the explicit `WHERE` filters;
   - index the policy columns. `organization_memberships` has no index led by `user_id` yet.
7. **Keep policies simple** (the SSAS lesson): equality or `IN` checks against indexed membership rows. Future complexity, such as teams or per-resource sharing, goes into membership data, not into policy logic.
8. **`TRUNCATE` and referential-integrity checks aren't subject to RLS.**
   - `TRUNCATE`: the integration-test cleanup fixture truncates through the app's sessionmaker, so cleanup and fixture seeding move to an owner-role connection, and the runtime role never gets `TRUNCATE`.
   - Referential-integrity checks: the `ON DELETE CASCADE` from organizations to memberships bypasses RLS, as every referential action does, so it removes every member's rows, including rows the caller can't see.
   - Unique and foreign-key violations are a known existence side channel. Random UUIDs and 404s keep the risk low, but constraint error text must never reach a client.
9. **No Python RLS library is mature enough to adopt.**
   - `sqlalchemy-tenants` uses one database role per tenant (session-level `SET SESSION ROLE`), needs permission to create roles at runtime, can't model one user in several organizations, and never tests for a pooled-connection leak. Its async tests use `NullPool`. Its sync tests use the default pool, and `test_full_str` commits in tenant sessions, which leaves the tenant role on the pooled connection: a commit keeps a `SET` made inside the transaction, and only a rollback undoes it.
   - The Django RLS libraries are all from 2025 or later.
   - Practitioners in the r/django thread mostly build their own.
   - `alembic_utils` (301 stars, since 2020) would add autogenerate for policies; the catalog guard test covers the same need without a dependency.
10. **Privileges the guard must see** (found 2026-10-15):
    - **`MAINTAIN`.** PostgreSQL 17 added an eighth table privilege, `MAINTAIN`. It allows `VACUUM`, `ANALYZE`, `CLUSTER`, `REINDEX`, `LOCK TABLE` and the statistics functions. Like `TRUNCATE`, it acts on the whole table, so RLS can't limit it, and `LOCK TABLE` alone could block every organization at once. The reader and the guard ask about it, and `app_runtime` never holds it. https://www.postgresql.org/docs/current/ddl-priv.html
    - **Column grants and grant options.** `has_table_privilege` sees whole-table grants only. Column-level grants need `has_any_column_privilege`, and grant options need `... WITH GRANT OPTION`. https://www.postgresql.org/docs/current/functions-info.html
    - **Owned objects.** A role whose privileges are inherited "should not own any SQL objects", or its members can take those objects over, so neither `app_runtime` nor the runtime login owns anything. https://www.postgresql.org/docs/current/sql-grant.html
    - **The ADMIN option** (found 2026-10-20). A membership granted `WITH ADMIN` lets the member grant the group to other roles. `pg_has_role(..., 'MEMBER WITH ADMIN OPTION')` tests for it, and the runtime login must not have it. https://www.postgresql.org/docs/current/functions-info.html
11. **`FORCE` holds a non-superuser owner to the policies** (found 2026-10-20, re-reading the research). Superusers and `BYPASSRLS` roles always bypass RLS; the table owner bypasses it *unless* `FORCE` is on (https://www.postgresql.org/docs/current/ddl-rowsecurity.html). In dev and test the owner is `postgres`, a superuser, so `FORCE` changes nothing there and no test can notice. On managed Postgres the owner is usually an ordinary role: the AWS sample relies on exactly that, "The RDS master user will be the owner of these tables and by default will bypass RLS" (`app/src/main/java/.../configuration/DatabaseInit.java`), which only holds because its `FORCE` is off. Supabase warns that a `SECURITY DEFINER` function "reading a table set to force row level security" is filtered again. So on such a deployment, with `FORCE` on:
    - Step 4's `SECURITY DEFINER` functions (the member count, `accept_invitation`) would be filtered, because they rely on their owner bypassing RLS;
    - Decision 3's privileged jobs (worker, CLI, seed script), which connect as the owner, would see and change nothing in the organization tables;
    - the same environment-dependent behaviour would surprise any future data migration on an organization table.

    Decision 2 is re-opened because of this.

## Design

### Where the security model lives

Per `agents.md` 4.7 (decided 2026-10-14), no grant, RLS switch or policy is hand-written into a migration:

- **One readable module is the source of truth:** `src/app/outbound/persistence_sqla/row_level_security.py`, next to the table mappings. It declares the role names, the classification of every table, the grants each class gets, which tables have RLS, and (from Step 3) every policy by name.
- **Migrations are generated from it.** A small Alembic autogenerate hook compares the module with the real database and writes the SQL that closes the gap, plus its exact reverse, into the new migration, the same way `make migration` turns a mapping into `CREATE TABLE`. The generated SQL is a frozen snapshot; migrations never import the module.
- **Policies are immutable:** changing one means a new name (`..._v2`). The generator then only compares policy names, never expression text, which Postgres rewrites when it stores it.
- **The catalog guard reads the same module,** so the database, the generator and the tests share one definition.

### Roles

- `postgres` stays the table owner and keeps running migrations.
- A no-login group role, `app_runtime` (`NOSUPERUSER NOBYPASSRLS`), receives grants listed per table, in the migration that creates or changes each table. There's no `ALTER DEFAULT PRIVILEGES`, so a new table is denied to the app until a migration grants it (OWASP "deny by default"):
  - `SELECT`, `INSERT`, `UPDATE` and `DELETE` on `users`, `auth_sessions`, `api_keys`, `organizations` and `organization_memberships`;
  - only `INSERT` on `event_outbox`: the web app only stages events, and the worker drains them as the owner (decided 2026-10-14, least privilege);
  - never `TRUNCATE`;
  - nothing on `alembic_version`;
  - no sequences are needed, since every primary key is a UUID.
- A login role joins that group, with new settings `POSTGRES_APP_USER` and `POSTGRES_APP_PASSWORD`. Only the web app and the public API connect with it. It inherits the group's privileges: a `NOINHERIT` login (as in https://github.com/ricofritzsche/multi-tenant-rls-demo) would be a member that can use none of the grants.
- **Who creates the roles:** roles belong to the whole Postgres cluster, not one database, so neither goes into migration history. An init script creates both in dev and test (Decision 1(a)), and ops in production. Postgres runs init scripts before any migration, so a migration couldn't create the group the login role has to join. The init script passes the password as a `psql` variable, never by text substitution (the AWS sample's `.replace("{{DB_APP_PASS}}", ...)` breaks on a quote), and is safe to run twice (`IF NOT EXISTS` against `pg_roles`). Every membership states its options explicitly, `INHERIT TRUE` and `SET FALSE` for the runtime login (one `GRANT app_runtime TO <runtime login> WITH ...` per option, since the syntax allows one option per `WITH` clause), instead of relying on the login's `INHERIT` attribute: a membership's `INHERIT` option only defaults to that attribute at the moment of the `GRANT`, and its `SET` option defaults to `TRUE` (https://www.postgresql.org/docs/current/sql-grant.html).
- **Startup self-check:** when the web and public-API processes start, they query `pg_roles` for `current_user`. They refuse to start if the role is a superuser, has `BYPASSRLS`, or owns any object (finding 10). That check runs in every environment (OWASP: check the deployed role, not only the configuration).

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

Every customer-facing policy is scoped `TO app_runtime` (the staff policies, under "Cross-organization staff access" below, are scoped to the staff roles), with each setting wrapped as `(SELECT NULLIF(current_setting('app.current_...', true), '')::uuid)`.

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
- **A known, low-risk race** (noted 2026-10-20): a policy that reads another table through a subquery, like the `organizations` membership check, reads that table with the statement's snapshot. PostgreSQL's RLS chapter shows a concurrent `SELECT ... FOR UPDATE` under `READ COMMITTED` seeing a row updated in the same moment the reader lost access. Membership removals and organization edits rarely race like this; noted, not designed around.
- **Views:** any future view over an organization-owned table is created `WITH (security_invoker = true)`. Postgres 18 is in use, so this is supported.

### Cross-organization staff access

- **Two no-login group roles,** both `NOSUPERUSER NOBYPASSRLS`, owning nothing:
  - `app_operator_read`: `SELECT` on the organization tables, through policies `FOR SELECT TO app_operator_read, app_operator_write USING (true)`. On `users` it gets column-level `SELECT` only, never the password hash.
  - `app_operator_write`: the same reads, plus `UPDATE` policies `TO app_operator_write` and **column-level** `UPDATE` grants naming exactly the fields staff may correct (in this template: an organization's name and description). No column that ties a row to an organization is ever granted, so a row can't be moved to another organization. No `INSERT` or `DELETE` across organizations, and never `TRUNCATE`.
  - Column grants fit here, unlike for invitations (Decision 6(b)): these roles serve only staff corrections, so a per-column grant is exactly the rule, not a side effect on the shared customer role.
  - The staff roles never get a table-level `SELECT` or `UPDATE` on a table with restricted columns: a column-level grant never narrows a table-level one ("A user may perform `SELECT`, `INSERT`, etc. on a column if they hold that privilege for either the specific column or its whole table", https://www.postgresql.org/docs/current/sql-grant.html), so one stray table-level grant would silently undo the column rules. PostgreSQL's own RLS chapter combines policies with column grants the same way (its `passwd` example).
- **One staff login** (new settings `POSTGRES_OPERATOR_USER` and `POSTGRES_OPERATOR_PASSWORD`), created `NOINHERIT` and a member of both groups (with `INHERIT FALSE` and `SET TRUE`, stated explicitly with one `GRANT ... WITH` per option, as for the runtime login). It can do nothing on its own. Each staff transaction starts with `SET LOCAL ROLE app_operator_read` or `SET LOCAL ROLE app_operator_write`, which lasts only for that transaction (the PostgREST pattern: a `NOINHERIT` authenticator switching role per request). `NOINHERIT` is deliberate here, the opposite of the runtime login: a staff transaction that forgets to pick a role can do nothing at all.
- **The app decides which role a transaction gets:** read use cases always use `app_operator_read`, even for staff who may also write; only write use cases use `app_operator_write`, after checking the write permission (Decision 8).
- **Every correction and every cross-organization read is logged** with who, which organization and record, and the required reason. An append-only audit table, written in the same transaction as each correction, was taken out of this plan's scope by the human maintainer on 2026-10-21; it is listed in `docs/plans/0-production-readiness-roadmap.md`.
- **Where staff access runs** (Decision 9(b)): in the existing web process, under its own route prefix and DI provider, and only when `POSTGRES_OPERATOR_*` is set; otherwise the staff routes aren't mounted and no staff engine exists. When staff access is on, the startup self-check also checks the staff login: not a superuser, no `BYPASSRLS`, owns nothing, `NOINHERIT`, and a member of exactly the two staff groups.
- **For high-risk writes,** a fork can replace a column grant with one narrow `SECURITY DEFINER` function per operation that writes the change (and, once the audit table exists, its audit row) in one statement (the Decision 6(a) pattern). Decision 10.

### Existing files this touches (flagged, per `agents.md` 3.1)

- `src/app/main/ioc/outbound.py`: one argument, to attach the listener to the sessions.
- `src/app/outbound/persistence_sqla/alembic/env.py` (the original author's): one argument, `process_revision_directives=...` on the `context.configure(...)` call in `do_run_migrations()`, so autogenerate also runs the security-model generator.
- Settings and loader: the runtime-role settings, each with its own env-var test in `test_loader.py` (`agents.md` 2.3).
- The web and public-API startup: the role self-check.
- `src/app/core/common/authorization/current_organization_service.py`: binding the verified organization, and WARNING logs with the user id and requested organization id on a 404 or 403.
- `src/app/core/commands/create_organization.py`: bind the new organization's id.
- `src/app/core/commands/accept_organization_invitation.py` (or its repository): the accept path, per Decision 6.
- `src/app/outbound/adapters/sqla_organization_reader.py`: the member-count function call.
- The error path for SQLSTATE 42501: logged at ERROR with context and alerted, not swallowed as a generic 503, with no SQL in the response.
- `tests/integration/with_infra/conftest.py`: cleanup and seeding through an owner-role engine.
- `env.example`, `docker-compose.yml` (with `${VAR:-default}` fallbacks, `agents.md` 5.4), and an init-script mount for the dev and test role.
- For staff access: the staff settings in the settings and loader, the staff roles in the init script, and, per Decision 9(b), the staff router and DI provider mounted in the existing web app only when the staff settings are present.

## Decisions for the human maintainer

1. **Where the login role is created:**
   - **(a) Recommended:** a Postgres init script for dev and test (run only on a fresh volume), and ops in production. No password enters migration history.
   - **(b)** In a migration, which puts a password in migration history.
2. **`FORCE ROW LEVEL SECURITY`:** recommended on, as cheap belt and braces in case the app ever connects as the owner. **Decided: on**, by the human maintainer, 2026-10-14.
   - **Re-opened 2026-10-20 (finding 11). Decided: (c), `FORCE` off**, by the human maintainer, 2026-10-20: "Best to avoid any infrastructure which behaves differently depending on where its deployed." The model declares RLS enabled and never forced; the planner removes `FORCE` wherever it finds it. Options considered:
     - **(a)** keep `FORCE` on, and require the owner to be a superuser or `BYPASSRLS` role, with the startup check verifying it;
     - **(b)** keep `FORCE` on, and give the `SECURITY DEFINER` functions their own `BYPASSRLS` owner (the privileged jobs stay broken on such a deployment unless they also use that role);
     - **(c) recommended:** turn `FORCE` off. The owner then bypasses RLS on every platform, so dev, test and production behave the same. `FORCE` is never a boundary against the owner, who can disable RLS or drop a policy at will; it only guards against the app connecting as the owner by mistake, and Step 8's startup check already refuses to start in that case (the request role owns objects), more loudly, in every environment.

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
8. **How the app knows a user is staff, and with which access.** **Decided: (b)**, by the human maintainer, 2026-10-14.
   - **(a)** Map the existing platform roles: `admin` reads across organizations, `super_admin` also writes. Nothing new to store, but every admin gets every organization's data, whether or not their job needs it.
   - **(b) Recommended:** an explicit staff grant per user, read or write, given and revoked by a `super_admin` and recorded with who granted it and when. OWASP asks for "an explicit platform permission" for cross-tenant access and least privilege; this is that, at the cost of one small table and its use cases.
9. **Which process serves staff and holds the staff credentials.** **Decided: (b)**, by the human maintainer, 2026-10-14: a separate service isn't worth the extra process for a small team, which already tracks the web process, the CLI and the Celery worker.
   - **Why (b) is acceptable:**
     - The web container already holds the owner's credentials (`docker-entrypoint.sh start` runs migrations and seeding as `postgres`, a superuser), so the staff credentials add little exposure until that follow-up lands.
     - The runtime login isn't a member of the staff groups, so customer-path SQL, even injected, can't `SET ROLE` to them; only code execution that reads the process environment could use the staff credentials.
     - OWASP's rule for cross-tenant paths ("explicit, separately authorized, and auditable") is still met: the explicit staff grant (Decision 8), the permission check in each use case, and the logs. What (b) gives up is process isolation, a defense-in-depth extra.
   - **The trade-off, recorded:** a full compromise of the web process exposes the staff credentials as well as the owner's (until migrations move out of the web container). A fork needing stronger isolation should do that follow-up first; it's the bigger win.
   - **Safeguards that come with (b):**
     - staff access is off unless `POSTGRES_OPERATOR_*` is set: without it, the staff routes aren't mounted and no staff engine exists, so a deployment that doesn't need staff access never holds the credentials;
     - the staff engines live in their own DI provider, injected only into staff use cases (like `PublicApiProvider` for the public API);
     - the staff routes sit under their own prefix and router, with their own permission checks.
   - **(a) Was recommended:** a separate, optional service running the same image with a staff entrypoint, behind its own Compose profile. Only that service's environment has `POSTGRES_OPERATOR_*`, so a compromised customer-facing process can't reach other organizations' data. A small deployment that doesn't need staff access simply doesn't run it, so the default stays web process plus Postgres (`agents.md` 4.1).
   - **(b)** Staff routes in the existing web process, on separate engines. No new service, but the customer-facing process holds credentials that read every organization.
   - **(c)** CLI only. Simplest, but no screens for staff, and the CLI connects as the owner (Decision 3), so RLS wouldn't apply.
10. **How staff writes are enforced in the database.** **Decided: (a)**, by the human maintainer, 2026-10-14.
    - **(a) Recommended for this template:** column-level `UPDATE` grants on `app_operator_write`, with each correction logged (the audit table is out of scope since 2026-10-21).
    - **(b)** One `SECURITY DEFINER` function per kind of correction, which writes the change and its audit row in one statement, with no direct `UPDATE` grant at all. Stricter, but one function per operation; documented as the option for a fork's high-risk writes.

## Proposed changes (each step: test first, confirmed RED, then code, confirmed GREEN)

### Order of work (decided 2026-10-21)

Steps 1 and 2 are done, and Step 3's SQL matrix covers `organization_memberships` fully. The rest no longer runs in step order. The SQL tests show each policy does what it says; only the app running as `app_user` shows the policies are the right ones (every real query still works, the context is bound at the right moments, nothing relies on seeing every row). So one use case goes through every layer first, and the work widens from there:

1. **Tracer bullet, a read:** an HTTP integration test for listing an organization's members, with that one app instance connected as `app_user`. It drives just what it needs: the `RowSecurityContext` port and adapter (Step 5), binding the user and the organization in the request path (Step 7), and any policy its queries hit (Step 3).
2. **Tracer bullet, a write that needs a privileged function:** accepting an invitation, through `accept_invitation` (Step 4).
3. **Widen route by route,** one TDD cycle each, for every organization route on both apps. Each remaining SQL matrix case and the member-count function (Steps 3 and 4) are written when a route needs them, with pool hygiene (Step 6) alongside.
4. **Flip the real engine to `app_user`** once every route passes as `app_user` in tests, then the startup self-check and each entrypoint's role (Steps 7 to 9).
5. **Step 15:** docs and human checks, then the commit, only once the whole feature works end to end.

Steps 10 to 14 (staff access) and user stories 6 and 7 are out of this plan's scope. Their design, here and in Decisions 8 to 10, carries over to their own plan, listed in `docs/plans/0-production-readiness-roadmap.md`.

1. **The runtime role exists and is unprivileged.**
   - Test: connect with the new credentials, and assert the role isn't a superuser, has no `BYPASSRLS`, owns no tables and inherits `app_runtime`'s privileges (`pg_has_role(..., 'USAGE')`; `MEMBER` alone is also true for a `NOINHERIT` login) but can't switch to it (`pg_has_role(..., 'SET')` false, from the explicit `SET FALSE`). RED: the new settings can't load, since nothing sets `POSTGRES_APP_*` yet.
   - Code: the init script creating both roles, the env vars, and the new loader (its `test_loader.py` test first). The per-table grants come in Step 2, whose guard tests them.
   - Added 2026-10-20 (finding 10): the same test also asserts the login doesn't hold the `ADMIN` option on `app_runtime`. A confirmation check.
2. **The security model as code, its generator, and the catalog guard.** (Policies moved to Step 3, so each is written test-first; the generator added per `agents.md` 4.7; both decided 2026-10-14.)
   - 2a. **The planner** (unit tests): given the declared model and the database's current state, it returns the SQL to apply and its exact reverse. An empty database gets every grant plus `ENABLE` and `FORCE ROW LEVEL SECURITY` on the organization-scoped tables; a database already in the declared state gets nothing; system tables get only what the model declares.
   - 2b. **The catalog reader** (integration test): reads each table's privileges for `app_runtime` and its RLS flags from a real database.
   - 2c. **The Alembic hook** (integration test): autogenerate writes the planner's SQL into a new migration's `upgrade()`, and the reverse into `downgrade()`.
   - 2d. **The catalog guard** (the tests below) reads `TABLE_CLASSIFICATION` from the module, and turns green through a migration generated with `make migration`.
   - Test: every table in the database is listed in an explicit classification, and every classified table exists: organization-scoped (`organizations`, `organization_memberships`), user-scoped (`auth_sessions`, `api_keys`), global (`users`), or system (`event_outbox`, `alembic_version`). A confirmation test: it passes on day one and guards future tables.
   - Test: every table with an `organization_id` column is classified organization-scoped. A confirmation test.
   - Test: every organization-scoped table has RLS enabled and forced (Decision 2). RED.
   - Test: `app_runtime` holds exactly `SELECT`, `INSERT`, `UPDATE` and `DELETE` on every organization-scoped, user-scoped and global table, only `INSERT` on `event_outbox`, nothing on `alembic_version`, and never `TRUNCATE`, `REFERENCES`, `TRIGGER` or `MAINTAIN`. RED.
   - Test (added 2026-10-15, finding 10): `app_runtime` holds no column-level grant beyond its table grants and nothing `WITH GRANT OPTION`, and neither it nor the runtime login owns any object. Confirmation tests. Alongside them, the catalog reader's test gains `MAINTAIN`, a genuine RED.
   - Test: no view reading an organization-scoped table lacks `security_invoker`. A confirmation test.
   - Code: the module, the planner, the reader and the hook; then one migration generated with `make migration`, holding the grants and `ENABLE`/`FORCE ROW LEVEL SECURITY` and their exact reverse. With RLS on and no policy yet, `app_runtime` sees nothing (default deny); the app still connects as `postgres` until Step 7, so nothing changes for it.
   - An existing dev database needs its volume recreated once: the migration needs `app_runtime`, which the init script creates only on a fresh volume.
3. **The isolation matrix at the SQL level, through the runtime role,** for both tables:
   - an unfiltered `SELECT` returns only the bound organization's rows;
   - nothing on a fresh connection, and nothing with no error on a reused pooled connection. This is a genuine RED without `NULLIF`;
   - a garbage context raises;
   - same-organization `INSERT`, `UPDATE` and `DELETE` succeed, proven with `RETURNING` (never "no error", which also passes when nothing matched);
   - cross-organization `UPDATE` and `DELETE` affect 0 rows, and an owner-role read shows the row unchanged. That read is a fresh query: sqlalchemy-tenants' `test_full_str` re-reads an already-consumed result, so its final check runs on an empty list and can never fail;
   - a cross-organization `INSERT`, or an `UPDATE` moving a row to another organization, fails with 42501. These statements use no `RETURNING`: with it, the `SELECT` policy also raises 42501 on the new row, so the test would pass without any `WITH CHECK` (found 2026-10-20);
   - the user branch returns exactly the user's own rows across organizations;
   - a pending invitee can read the organization's row;
   - the `ON DELETE CASCADE` removes every member's rows.
   - **Migrations** (decided 2026-10-15, option (b)): Step 3's policies go into one migration. Each time a policy is added or changed, the previous uncommitted Step 3 migration is deleted and `make migration` regenerates it from the module. Once committed with the plan, it's frozen like any other migration, and from then on a changed policy gets a new name.
   - Code: the policies (one per command, `TO app_runtime`), declared in the security-model module and generated into migrations (the planner and reader extended to policies by name), the index on `organization_memberships.user_id` (declared in its mapping), and the guard's "at least one policy per organization-scoped table" check, each added after the matrix test that needs it.
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
   - Test: an error from `set_config` (or, for staff, `SET LOCAL ROLE`) propagates; the adapter never catches it, so it surfaces as a 500 and reaches the existing alert. A swallowed failure wouldn't leak rows, since the request would just see none, but it would turn a real bug into silent empty pages. Both samples that swallow it show the risk: the AWS sample logs a failed `SET SESSION` and carries on, and sqlalchemy-tenants ignores every role-switch error except "does not exist".
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
8. **The startup self-check.** Test: starting with a superuser, a `BYPASSRLS` role or a role owning any object refuses to start; starting with the runtime role succeeds. Code: the check in the web and public-API startup.
   - Note (2026-10-20): PostgreSQL's `row_security_active(table)` reports whether RLS really applies to the current role on that table; checking it for every organization-scoped table makes a direct extra assertion, beyond the role attributes. If Decision 2 becomes (a), this step also checks the owner can bypass RLS.
9. **Pin each entrypoint's role.** Tests: the worker and CLI connect as `POSTGRES_USER`; the web app and public API connect as the runtime role.
10. **(Out of scope since 2026-10-21: Steps 10 to 14 move to their own plan; see "Order of work".) The staff roles exist and are unprivileged.**
    - Test: the staff login connects; it isn't a superuser, has no `BYPASSRLS`, owns nothing, is `NOINHERIT` (`pg_has_role(..., 'USAGE')` false for both groups) and can `SET LOCAL ROLE` to each group (`pg_has_role(..., 'SET')` true). With no role chosen, reading an organization table fails with 42501. RED: the staff settings can't load.
    - Code: the staff settings and loader (their `test_loader.py` tests first), the staff roles in the init script, the env vars.
11. **Staff reads, through the read role.**
    - Test: after `SET LOCAL ROLE app_operator_read`, an unfiltered `SELECT` returns rows from every organization; `INSERT`, `UPDATE` and `DELETE` each fail with 42501; reading the password-hash column fails with 42501; no staff role has `TRUNCATE`.
    - Code: the grants and `SELECT` policies migration.
    - Note (2026-10-20): a role with only column-level `SELECT` can't run `SELECT *` on that table (Supabase, https://supabase.com/docs/guides/database/postgres/column-level-security). So the staff readers select explicit columns; they can't load the full `User` mapping, which includes the password hash.
12. **Staff corrections, through the write role.**
    - Test: after `SET LOCAL ROLE app_operator_write`, updating a granted field in any organization succeeds, proven with `RETURNING` and a fresh owner-role read; updating any other field, or a column tying a row to an organization, fails with 42501; `INSERT` and `DELETE` fail; and the catalog shows no table-level `UPDATE` for either staff role on `organizations`, and no table-level `SELECT` on `users`, so no table-level grant overrides the column grants.
    - Code: the column grants and the `UPDATE` policies (generated with `make migration`).
13. **Staff use cases and their permission checks,** per Decision 8.
    - Tests (unit, with fakes): a non-staff user is refused; a read-only staff member can read but not correct; a correction without a reason is refused; a correction is logged with who, what and why; denials log a WARNING with the user id.
    - Tests (integration): read use cases run under `app_operator_read`, and write use cases under `app_operator_write`.
    - Code: the ports, adapters and use cases for the template's generic examples (list organizations across all organizations, correct an organization's name or description), with the `SET LOCAL ROLE` applied by the staff adapter at the start of each transaction.
14. **Staff access in the web process, and its safeguards,** per Decision 9(b).
    - Tests:
      - the runtime login can't `SET ROLE` to either staff group (42501);
      - with no `POSTGRES_OPERATOR_*` set, the app starts, the staff routes return 404, and no staff engine is built;
      - a customer request never builds a staff engine, even with staff access on;
      - with staff access on, the startup self-check refuses a superuser, a `BYPASSRLS` role, a table owner, an `INHERIT` login or a login in any other group, and accepts the real staff login.
    - Code: the staff router under its own prefix, the staff DI provider, and mounting both only when the staff settings are present.
15. **Docs and human checks:**
    - curl as two users against each route;
    - `psql` as the runtime role: with no context, `SELECT` returns 0 rows; inside `BEGIN`/`set_config`/`COMMIT`, only that organization's rows; a cross-organization `INSERT` fails;
    - `psql` as the runtime role: moving a membership to another organization fails with 42501 both without a `WHERE` (refused by the UPDATE policy's `WITH CHECK` alone, as the matrix test does it) and with one (where the SELECT policy also checks the new row);
    - `EXPLAIN ANALYZE` of the policy queries as the runtime role;
    - the same role query the startup check runs, against production;
    - a PgBouncer note: transaction-local settings work in transaction pooling mode, session settings don't;
    - backups and restores run as the owner and are cross-tenant by nature, so restoring a single organization means restoring into a separate database and copying that organization's rows;
    - the wiki, the `CHANGELOG.md` entry and version, and the roadmap and README checklist. The wiki page `docs/wiki/content/core-patterns/row-level-security.md` is already behind (2026-10-20): it says "Step 1 of 15", and shows `CREATE POLICY` as "planned, Step 2" (policies moved to Step 3).

## Follow-ups and non-goals

Out of scope here, recorded so they aren't lost (OWASP sections in brackets):
- When rate limiting lands (roadmap P0), add an organization dimension for organization routes, starting with invitation sending, so one organization can't spam invitations (5).
- When caching lands, cache keys for organization data include the organization id, authorization runs before a cache read, and shared entries live in an explicit global namespace (4).
- Before any organization *write* reaches the public API, API keys need an explicit organization scope (5); see Decision 7 for reads.
- The invitation email handler re-checks, before sending, that the invitation is still pending, so a revoked invitation isn't emailed (5, stale permission decisions).
- Pseudonymize the invitee's email in the invitation handler's logs, for example log the membership id instead (8).
- A retention, deletion and audit policy for deleted organizations (7).
- File storage (`docs/plans/12-file-storage.md`) uses organization-scoped object keys, authorizes before signing any URL, and validates key structure (6).
- Search (`docs/plans/11-search.md`) under RLS: a user's own condition whose function or operator isn't `LEAKPROOF` is evaluated after the policy's conditions (https://www.postgresql.org/docs/current/sql-createpolicy.html, Notes), which can stop its index being used. Search queries over organization tables get an `EXPLAIN ANALYZE` as the runtime role, as Step 15 does for the policies.
- Per-organization encryption keys, and an audit-log retention and access policy: non-goals for now (7, 8).
- The web container still holds the owner's credentials, because `docker-entrypoint.sh start` runs migrations and the seed script before the app. Move both into a separate one-shot process, so a compromised web process can't read them (OWASP: "Reserve privileged connections for migrations and explicitly authorized administrative jobs") (2). The AWS sample shows the cost: its app container gets both passwords, and its unauthenticated `/admin/**` pages run on the owner connection.

## Verification plan

- `make check` at every GREEN; `make test-docker` after every database or wiring step.
- Human checks, written into this plan as each step lands, in the `docs/plans/agents.md` 1.3 format.
- **Every human check is a pair: `curl`, then SQL** (decided by the human maintainer, 2026-10-15).
  - The `curl` command proves the behaviour through the real request path, where the application-layer checks and RLS work together.
  - The SQL check proves the database layer on its own. It runs in `psql` as the runtime role (`app_user`), as `BEGIN; SELECT set_config(...); <query>; COMMIT;`, with the same "forgotten filter" query the matrix tests use (no `WHERE organization_id = ...`).
  - Why both: a request can return the right rows even with RLS broken, because the app's own `WHERE` clauses and membership checks hide the gap. Only the SQL half shows that the policies themselves isolate the data.
  - Each pair shows an allowed case and a denied case where both apply. The SQL output prints whole rows (`psql -x`), per `agents.md` 1.3.
  - A read-back that proves a write was stored runs as the owner (`postgres`), so a policy can't hide a row that really is there.
  - The exact `psql` command (which container, which login) is settled when the first checks are written, using a real entrypoint (`agents.md` 1.2).
