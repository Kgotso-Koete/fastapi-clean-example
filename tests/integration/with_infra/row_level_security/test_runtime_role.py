from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.main.config.loader import load_postgres_runtime_role_settings, load_postgres_settings

# docs/plans/14-row-level-security.md, Step 1. The web app and the public API
# will connect as an unprivileged runtime role, so that Postgres Row-Level
# Security policies actually apply to their queries. Postgres exempts three
# kinds of role from every policy: superusers, roles with the BYPASSRLS
# attribute, and the owner of the table. This test logs in with the runtime
# role's own credentials and proves it is none of those, and that it really
# receives the privileges granted to the app_runtime group role, which every
# grant and policy in this plan targets.

_GROUP_ROLE = "app_runtime"

# One row describing the role this connection logged in as. pg_roles holds
# each role's attributes; pg_tables lists every table with its owner (it
# includes partitioned tables); pg_has_role(..., 'USAGE') is true only when
# the role can use the group's privileges without a SET ROLE first, which
# is how the app will use them; pg_has_role(..., 'SET') is true when the
# role may switch to the group with SET ROLE, which the runtime login never
# needs (its membership is granted with INHERIT TRUE and SET FALSE);
# 'MEMBER WITH ADMIN OPTION' is true when the role may grant the group to
# other roles (or revoke it), which the runtime login must never be able to do.
_DESCRIBE_CURRENT_ROLE = text(
    """
    SELECT
        current_user AS role_name,
        r.rolsuper AS is_superuser,
        r.rolbypassrls AS bypasses_rls,
        (SELECT count(*) FROM pg_tables WHERE tableowner = current_user) AS owned_tables,
        pg_has_role(current_user, :group_role, 'USAGE') AS inherits_group,
        pg_has_role(current_user, :group_role, 'SET') AS can_switch_to_group,
        pg_has_role(current_user, :group_role, 'MEMBER WITH ADMIN OPTION') AS can_grant_group
    FROM pg_roles AS r
    WHERE r.rolname = current_user
    """
)


async def test_the_runtime_role_is_an_ordinary_login_that_inherits_app_runtime() -> None:
    # Same host, port and database as the owner's settings; only the login
    # changes. model_copy builds a PostgresSettings carrying the runtime
    # role's credentials, so its existing .dsn property builds the URL.
    owner_settings = load_postgres_settings()
    runtime_role_settings = load_postgres_runtime_role_settings()
    runtime_role_dsn = owner_settings.model_copy(
        update={"USER": runtime_role_settings.USER, "PASSWORD": runtime_role_settings.PASSWORD},
    ).dsn

    engine = create_async_engine(runtime_role_dsn)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(_DESCRIBE_CURRENT_ROLE, {"group_role": _GROUP_ROLE})
            role = result.mappings().one()
    finally:
        await engine.dispose()

    # Really logged in as the configured runtime role, so a silent fallback
    # to the owner's login (postgres) can't pass this test by accident.
    assert role["role_name"] == runtime_role_settings.USER
    # A superuser ignores every policy, even with FORCE ROW LEVEL SECURITY.
    assert role["is_superuser"] is False
    # BYPASSRLS skips every policy too.
    assert role["bypasses_rls"] is False
    # A table's owner bypasses its policies unless FORCE is on, so the
    # runtime role must own nothing; the owner stays postgres.
    assert role["owned_tables"] == 0
    # The role uses app_runtime's privileges directly. 'MEMBER' alone would
    # also be true for a NOINHERIT login, which could use none of them.
    assert role["inherits_group"] is True
    # Least privilege: the login uses app_runtime's grants but can't become
    # app_runtime. This also catches the init script losing its explicit
    # membership options, since Postgres's default would allow SET ROLE.
    assert role["can_switch_to_group"] is False
    # A confirmation check (added 2026-10-20, plan 14 Step 1):
    # with the ADMIN option, the login could hand app_runtime's grants to any
    # other role, outside the security model. The init script never grants
    # it, and Postgres's default is FALSE; this catches anyone adding it.
    assert role["can_grant_group"] is False
