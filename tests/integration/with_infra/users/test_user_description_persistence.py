import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from tests.integration.with_infra.factories import create_user

# Proves users.description is wired end to end: the column exists (the
# migration), it's mapped to User.description, and ValueObjectType turns a
# Description into text and back, with NULL for none
# (docs/plans/10-profile-editing.md, Step 2). The conversion itself is unit
# tested in tests/unit/outbound/persistence_sqla/test_value_object_type.py.


async def _reload(it_session: AsyncSession, user: User) -> User:
    # Drop every object from the session's identity map, so the read has to
    # actually SELECT the row back from Postgres rather than being handed the
    # same in-memory object.
    user_id = user.id_
    it_session.expunge_all()
    reloaded = await it_session.get(User, user_id)
    assert reloaded is not None
    return reloaded


async def test_a_user_saved_with_a_description_reads_it_back(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user = create_user(it_user_service)
    user.description = Description("Genius, billionaire, philanthropist.")
    it_session.add(user)
    await it_session.commit()

    reloaded = await _reload(it_session, user)

    assert reloaded.description == Description("Genius, billionaire, philanthropist.")


async def test_a_user_saved_without_a_description_reads_back_none(
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Every user created before or without this feature: the column is NULL,
    # and the entity reads None, never an error.
    user = create_user(it_user_service)
    it_session.add(user)
    await it_session.commit()

    reloaded = await _reload(it_session, user)

    assert reloaded.description is None


@pytest.mark.parametrize(
    "new_description",
    [
        pytest.param("I am Iron Man.", id="changed"),
        pytest.param(None, id="cleared"),
    ],
)
async def test_changing_a_loaded_users_description_persists_it(
    it_session: AsyncSession,
    it_user_service: UserService,
    new_description: str | None,
) -> None:
    # A loaded User is tracked by the session, so a command changes the
    # attribute and commits, with no separate "save" call. Clearing writes
    # NULL (decision 3: null clears it).
    user = create_user(it_user_service)
    user.description = Description("Genius, billionaire, philanthropist.")
    it_session.add(user)
    await it_session.commit()
    loaded = await _reload(it_session, user)

    loaded.description = Description(new_description) if new_description is not None else None
    await it_session.commit()

    reloaded = await _reload(it_session, loaded)
    assert reloaded.description == (Description(new_description) if new_description is not None else None)
