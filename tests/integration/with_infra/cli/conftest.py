import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.types_ import UserRole
from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.outbound.persistence_sqla.mappings.all import map_tables
from tests.integration.with_infra.factories import (
    create_raw_password,
    create_super_admin_with_password,
    create_user_with_password,
)


@pytest.fixture(autouse=True)
def _it_cli_mapped_tables() -> None:
    """
    Other integration suites get map_tables() for free: every one of their
    tests goes through it_client, whose FastAPI lifespan calls it. Some CLI
    tests (e.g. an unknown-username/wrong-password case) invoke root_group
    directly via CliRunner and never touch it_session/it_client at all, so
    SqlaUserFinder's `select(User)` would otherwise run before User is
    mapped. map_tables() is idempotent (see its own no-op guard), so calling
    it unconditionally here is safe even when another fixture also does.
    """
    map_tables()


@pytest.fixture
def it_cli_raw_password() -> str:
    return create_raw_password()


@pytest.fixture
async def it_cli_admin(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_cli_raw_password: str,
) -> User:
    """
    A real admin, seeded directly via UserService/AsyncSession -- unlike
    tests/integration/with_infra/users/conftest.py's it_admin, this never
    logs in over HTTP: the CLI authenticates with the raw username/password
    directly, so the test only needs the plaintext password it was created
    with, not a session cookie.
    """
    admin = await create_user_with_password(it_user_service, raw_password=it_cli_raw_password, role=UserRole.ADMIN)
    it_session.add(admin)
    await it_session.commit()
    return admin


@pytest.fixture
async def it_cli_user(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_cli_raw_password: str,
) -> User:
    """A real, non-admin user -- for asserting that admin-only commands reject it."""
    user = await create_user_with_password(it_user_service, raw_password=it_cli_raw_password, role=UserRole.USER)
    it_session.add(user)
    await it_session.commit()
    return user


@pytest.fixture
async def it_cli_super_admin(
    it_session: AsyncSession,
    it_user_service: UserService,
    it_cli_raw_password: str,
) -> User:
    """A real super admin -- grant-admin/revoke-admin are super-admin-only."""
    super_admin = await create_super_admin_with_password(it_user_service, raw_password=it_cli_raw_password)
    it_session.add(super_admin)
    await it_session.commit()
    return super_admin
