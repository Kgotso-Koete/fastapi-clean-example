"""
Dev-only DB seeding: creates ~10 test user accounts (mix of user/admin/
super_admin roles) so manual testing has ready-made fixture data instead of
requiring a fresh sign-up every time (e.g. testing "delete user" is trivial
when a disposable seeded user already exists).

Chain of events that leads here, starting from `make upd`:
1. `Makefile`'s `upd` target first runs its `docker-env` prerequisite, which
   invokes `scripts/makefile/docker_env.sh`. That script regenerates `.env`
   by concatenating `env.example` then `.secrets` (later file wins on
   duplicate keys) -- this is where `SEED_DB_WITH_TEST_DATA` and
   `ENVIRONMENT` end up in `.env`.
2. `Makefile`'s `upd` target then runs `docker compose up -d --build
   --force-recreate`, which builds/starts every service defined in
   `docker-compose.yml`. The `app` service only starts once `db_pg` reports
   healthy (`depends_on: condition: service_healthy`).
3. When the `app` container actually starts, Docker runs the image's
   `ENTRYPOINT` (set in `Dockerfile`) -- that's `docker-entrypoint.sh`, with
   the command args landing in its `case "$1" in start) ... esac` branch.
4. Inside that branch: `alembic upgrade head` runs first (creates the
   `users` table and everything else migrations define). Then, only if
   `ENVIRONMENT` isn't `"production"` and `SEED_DB_WITH_TEST_DATA` is
   `"true"`, `docker-entrypoint.sh` runs `python scripts/seed_db.py` --
   this file. Finally `exec uvicorn app.main.run:make_app ...` replaces the
   shell process and starts serving HTTP.

So this script always runs after migrations have already created the
schema, and only on `app` container startup -- never as its own Docker
Compose service, and never invoked by any Makefile target directly.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import asgi_lifespan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.common.entities.types_ import UserRole
from app.core.common.factories.id_factory import create_user_id
from app.core.common.services.user import UserService
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.main.run import make_app
from app.outbound.persistence_sqla.mappings.user import users_table

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SeedUser:
    username: str
    email: str
    phone_number: str
    password: str
    role: UserRole


# Each password is deliberately different in shape (letter-heavy, digit-heavy,
# special-char-heavy, near the 12-char minimum, near the far end) so manual
# testing exercises a variety of valid password compositions at login, not
# just one repeated value.
SEED_USERS: list[SeedUser] = [
    SeedUser("ororo-munroe", "ororo.munroe@xmen.org", "27821000001", "Storm!!@@##%%1", UserRole.SUPER_ADMIN),
    SeedUser("miles-morales", "miles.morales@visionacademy.edu", "27821000002", "WebSlingerHero1!", UserRole.ADMIN),
    SeedUser("jean-grey", "jean.grey@xmen.org", "27821000003", "Phoenix19864202!", UserRole.ADMIN),
    SeedUser("john-stewart", "john.stewart@greenlanternscorps.org", "27821000004", "GreenLantern#2024", UserRole.ADMIN),
    SeedUser("matt-murdock", "matt.murdock@nelsonmurdock.com", "27821000005", "Daredevil1!!", UserRole.USER),
    SeedUser("wade-wilson", "wade.wilson@mercforhire.com", "27821000006", "MaximumEffort2024!!!", UserRole.USER),
    SeedUser("charles-xavier", "charles.xavier@xmen.org", "27821000007", "Cerebro#Mutant42", UserRole.USER),
    SeedUser(
        "jessica-jones",
        "jessica.jones@alias-investigations.com",
        "27821000008",
        "AliasInvestig8203!",
        UserRole.USER,
    ),
    SeedUser("luke-cage", "luke.cage@harlemheroes.com", "27821000009", "PowerMan2024!", UserRole.USER),
    SeedUser("danny-rand", "danny.rand@rand-corp.com", "27821000010", "Iron$Fist_KunLun1!", UserRole.USER),
]


async def _seed_one(
    session: AsyncSession,
    user_service: UserService,
    seed: SeedUser,
) -> None:
    already_exists = (
        await session.execute(select(users_table.c.id).where(users_table.c.username == seed.username))
    ).first()
    if already_exists is not None:
        logger.info("Seed user %s already exists, skipping.", seed.username)
        return

    # UserService.create_user (and create_user_with_raw_password) refuses to
    # assign a "system" role directly (role.is_system guard) -- super_admin
    # can only ever be set by overriding the attribute after the fact, the
    # same way tests/integration/with_infra/factories.py::create_super_admin_with_password
    # does it. That's the only precedent for this role anywhere in the codebase.
    creation_role = UserRole.USER if seed.role is UserRole.SUPER_ADMIN else seed.role
    user = await user_service.create_user_with_raw_password(
        user_id=create_user_id(),
        username=Username(seed.username),
        email=Email(seed.email),
        phone_number=PhoneNumber(seed.phone_number),
        raw_password=RawPassword(seed.password),
        now=UtcDatetime(datetime.now(UTC)),
        role=creation_role,
        is_active=True,
    )
    if seed.role is UserRole.SUPER_ADMIN:
        user.role = UserRole.SUPER_ADMIN
    session.add(user)
    logger.info("Seeded %s (%s)", seed.username, seed.role.value)


async def main() -> None:
    app = make_app()
    async with asgi_lifespan.LifespanManager(app):
        container = app.state.dishka_container
        user_service = await container.get(UserService)
        session_maker = await container.get(async_sessionmaker[AsyncSession])
        async with session_maker() as session:
            for seed in SEED_USERS:
                await _seed_one(session, user_service, seed)
            await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
