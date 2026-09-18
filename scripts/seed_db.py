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
from datetime import UTC, datetime, timedelta

import asgi_lifespan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.common.entities.api_key import ApiKey
from app.core.common.entities.types_ import UserId, UserRole
from app.core.common.factories.api_key_id_factory import create_api_key_id
from app.core.common.factories.id_factory import create_user_id
from app.core.common.factories.raw_api_key_factory import generate_raw_api_key
from app.core.common.services.user import UserService
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.username import Username
from app.core.common.value_objects.utc_datetime import UtcDatetime
from app.main.config.settings import PasswordHasherSettings
from app.main.run import make_app
from app.outbound.adapters.hmac_sha256_api_key_hasher import HmacSha256ApiKeyHasher
from app.outbound.persistence_sqla.mappings.api_key import api_keys_table
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
    # Public-API-key testing fixtures -- each of these 5 also gets a
    # SeedApiKey below (see SEED_API_KEYS), some valid and some already
    # expired, so manual testing of the public API has ready-made accounts
    # for both the "key works" and "key expired" paths without having to
    # issue a key by hand first.
    SeedUser("peter-parker", "peter.parker@dailybugle.com", "27821000011", "SpideySense2024!", UserRole.USER),
    SeedUser("tony-stark", "tony.stark@starkindustries.com", "27821000012", "ImIronMan#3000", UserRole.USER),
    SeedUser("natasha-romanoff", "natasha.romanoff@shield.gov", "27821000013", "BlackWidow!!Red1", UserRole.USER),
    SeedUser("diana-prince", "diana.prince@themyscira.org", "27821000014", "AmazonWarrior$99", UserRole.USER),
    SeedUser("bruce-wayne", "bruce.wayne@wayneenterprises.com", "27821000015", "IAmTheNight2024!!", UserRole.USER),
]


@dataclass(frozen=True, slots=True)
class SeedApiKey:
    username: str  # must match a SeedUser.username above
    label: str
    is_expired: bool


# 3 valid, 2 already expired -- exercises both the "key works" and "key
# expired" paths in the public API without anyone having to issue a key by
# hand first. Raw keys are shown exactly once, so they're logged below at
# seeding time (see _seed_api_key) -- fine for dev-only fixture data, same
# reasoning as SEED_USERS' plaintext passwords above.
SEED_API_KEYS: list[SeedApiKey] = [
    SeedApiKey("peter-parker", "Spider-Sense Dev Key", is_expired=False),
    SeedApiKey("tony-stark", "Stark Industries CI Key", is_expired=False),
    SeedApiKey("natasha-romanoff", "SHIELD Field Ops Key", is_expired=False),
    SeedApiKey("diana-prince", "Themyscira Legacy Key", is_expired=True),
    SeedApiKey("bruce-wayne", "Wayne Enterprises Night Key", is_expired=True),
]


async def _seed_one(
    session: AsyncSession,
    user_service: UserService,
    seed: SeedUser,
) -> UserId:
    already_exists = (
        await session.execute(select(users_table.c.id).where(users_table.c.username == seed.username))
    ).first()
    if already_exists is not None:
        logger.info("Seed user %s already exists, skipping.", seed.username)
        return UserId(already_exists.id)

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
    return user.id_


async def _seed_api_key(
    session: AsyncSession,
    api_key_hasher: HmacSha256ApiKeyHasher,
    user_id: UserId,
    seed: SeedApiKey,
) -> None:
    already_exists = (
        await session.execute(
            select(api_keys_table.c.id).where(
                api_keys_table.c.user_id == user_id,
                api_keys_table.c.label == seed.label,
            )
        )
    ).first()
    if already_exists is not None:
        logger.info("Seed API key %r already exists, skipping.", seed.label)
        return

    # Mirrors IssueApiKey.execute's own construction exactly (raw key ->
    # hash + "ak_" + 8-char prefix), just without going through that
    # command's username/password re-authentication -- this script already
    # knows which user it's minting for.
    now = UtcDatetime(datetime.now(UTC))
    expires_at = UtcDatetime(now.value + timedelta(days=-1 if seed.is_expired else 30))
    raw_key = generate_raw_api_key()
    api_key = ApiKey(
        id_=create_api_key_id(),
        user_id=user_id,
        key_hash=api_key_hasher.hash(raw_key),
        key_prefix=raw_key[:11],
        label=seed.label,
        created_at=now,
        expires_at=expires_at,
    )
    session.add(api_key)
    # Raw key is shown exactly once, ever, and this script's only "once" is
    # this log line -- fine for dev-only fixture data, same reasoning as
    # SEED_USERS' plaintext passwords above.
    logger.info(
        "Seeded %s API key %r for %s: %s",
        "expired" if seed.is_expired else "valid",
        seed.label,
        seed.username,
        raw_key,
    )


async def main() -> None:
    app = make_app()
    async with asgi_lifespan.LifespanManager(app):
        container = app.state.dishka_container
        user_service = await container.get(UserService)
        session_maker = await container.get(async_sessionmaker[AsyncSession])
        password_hasher_settings = await container.get(PasswordHasherSettings)
        # Constructed directly rather than resolved from the container --
        # ApiKeyHasher is only bound in PublicApiProvider (the public API's
        # own container, see src/app/main/ioc/public_api.py), and this
        # script only ever builds the private app's container via
        # make_app(). Mirrors that provider's own construction exactly.
        api_key_hasher = HmacSha256ApiKeyHasher(pepper=password_hasher_settings.PEPPER.encode())

        async with session_maker() as session:
            user_ids_by_username: dict[str, UserId] = {}
            for seed in SEED_USERS:
                user_ids_by_username[seed.username] = await _seed_one(session, user_service, seed)
            # User and ApiKey have no SQLAlchemy relationship() between them
            # (api_key.py maps user_id as a plain FK column, not a
            # relationship) -- without one, the unit-of-work has no ordering
            # dependency to enforce between the two mapped classes, so with
            # autoflush=False (see outbound.py) a single flush at commit can
            # emit the api_keys INSERT statements before the users INSERT
            # statements, tripping the FK constraint. Flushing here first
            # forces every user row to actually exist (same transaction,
            # still uncommitted) before any api_keys row is built to
            # reference one.
            await session.flush()
            for seed_key in SEED_API_KEYS:
                await _seed_api_key(session, api_key_hasher, user_ids_by_username[seed_key.username], seed_key)
            await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
