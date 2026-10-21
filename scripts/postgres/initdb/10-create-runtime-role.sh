#!/bin/bash
# Creates the unprivileged database roles the web app and public API connect
# as, so Postgres Row-Level Security policies actually apply to them
# (docs/plans/14-row-level-security.md, Step 1 and Decision 1(a)).
#
# The official Postgres image runs every script in /docker-entrypoint-initdb.d
# exactly once, on a brand-new data folder, as POSTGRES_USER (the owner, a
# superuser). docker-compose.yml mounts this folder there for dev and test.
# A production database gets the same roles from ops, never from a migration:
# roles belong to the whole Postgres cluster, and a password must never enter
# migration history.
#
# What it creates (each step is safe to run twice):
#   - app_runtime: a NOLOGIN group with no superuser and no BYPASSRLS. Every
#     table grant and RLS policy targets this group.
#   - the login role named by POSTGRES_APP_USER, the same kind of ordinary
#     role, with POSTGRES_APP_PASSWORD.
#   - its membership in app_runtime, with INHERIT TRUE (it uses the group's
#     grants directly) and SET FALSE (it can never switch to the group).
#     Both options are stated explicitly, one GRANT per option as the GRANT
#     syntax requires, instead of relying on Postgres's defaults.
#
# Name and password are passed in as psql variables (--set) and quoted by
# format(): %I for a name, %L for a value. They are never pasted into the SQL
# text, so a quote in either can't break or inject into it. psql variables
# aren't expanded inside DO $$...$$ blocks, which is why each statement is
# built with SELECT format(...) and run with \gexec instead.
#
# ON_ERROR_STOP makes any failure stop the database container from starting,
# rather than leaving it half set up.
psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set app_user="$POSTGRES_APP_USER" \
    --set app_password="$POSTGRES_APP_PASSWORD" <<'EOSQL'
SELECT 'CREATE ROLE app_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS'
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_runtime')
\gexec

SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'app_user',
    :'app_password'
)
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = :'app_user')
\gexec

SELECT format('GRANT app_runtime TO %I WITH INHERIT TRUE', :'app_user')
\gexec

SELECT format('GRANT app_runtime TO %I WITH SET FALSE', :'app_user')
\gexec
EOSQL
