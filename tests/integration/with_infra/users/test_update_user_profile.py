from uuid import uuid4

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.types_ import UserRole
from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import (
    create_raw_password,
    create_super_admin,
    create_user,
    create_user_with_password,
)
from tests.integration.with_infra.users.constants import USERS_ENDPOINT

# PATCH /api/v1/users/{user_id}/profile/ (docs/plans/10-profile-editing.md,
# Step 6): a platform admin edits another user's profile through
# UpdateUserProfile, authorized like SetUserPassword. Every refusal re-reads
# the target and checks nothing changed, not just the status code.


def _profile_endpoint(user_id: object) -> str:
    return f"{USERS_ENDPOINT}{user_id}/profile/"


async def _persist_target(it_session: AsyncSession, target: User) -> User:
    target.description = Description("Friendly neighborhood photographer.")
    it_session.add(target)
    await it_session.commit()
    return target


def _snapshot(user: User) -> tuple[str, str, str, str | None]:
    return (
        user.username.value,
        user.email.value,
        user.phone_number.value,
        user.description.value if user.description is not None else None,
    )


async def _assert_unchanged(it_session: AsyncSession, user: User, before: tuple[str, str, str, str | None]) -> None:
    # Re-read from Postgres, so this proves nothing was committed.
    await it_session.refresh(user)
    assert _snapshot(user) == before


async def test_returns_200_and_an_admin_edits_a_users_profile_with_no_password(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_admin: User,
    it_user_service: UserService,
) -> None:
    # The role hierarchy is the authorization, so even the email changes
    # without the target's password.
    target = await _persist_target(it_session, create_user(it_user_service))

    r = await it_client.patch(
        _profile_endpoint(target.id_),
        json={
            "username": "spider-man",
            "email": "spidey@example.com",
            "phone_number": "0821000099",
            "description": "Edited by an admin.",
        },
    )

    assert r.status_code == 200
    assert r.json()["username"] == "spider-man"
    await it_session.refresh(target)
    assert _snapshot(target) == ("spider-man", "spidey@example.com", "27821000099", "Edited by an admin.")


async def test_returns_200_and_null_clears_a_users_description(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_admin: User,
    it_user_service: UserService,
) -> None:
    target = await _persist_target(it_session, create_user(it_user_service))

    r = await it_client.patch(_profile_endpoint(target.id_), json={"description": None})

    assert r.status_code == 200
    await it_session.refresh(target)
    assert target.description is None


async def test_returns_401_when_not_authenticated(
    it_client: httpx2.AsyncClient,
) -> None:
    r = await it_client.patch(_profile_endpoint(uuid4()), json={"description": "Hello"})

    assert r.status_code == 401


async def test_returns_403_and_changes_nothing_when_a_plain_user_uses_it_even_on_themselves(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A USER manages no one; they edit themselves through /account/profile/.
    password = create_raw_password()
    user = await _persist_target(it_session, await create_user_with_password(it_user_service, raw_password=password))
    await authenticate(it_client, user.username.value, password)
    before = _snapshot(user)

    r = await it_client.patch(_profile_endpoint(user.id_), json={"description": "Via the admin route."})

    assert r.status_code == 403
    await _assert_unchanged(it_session, user, before)


async def test_returns_403_and_changes_nothing_when_an_admin_targets_their_own_level_or_above(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_admin: User,
    it_user_service: UserService,
) -> None:
    # Otherwise an admin could take over another admin's or a super admin's
    # account by changing its email.
    other_admin = await _persist_target(it_session, create_user(it_user_service, role=UserRole.ADMIN))
    super_admin = await _persist_target(it_session, create_super_admin(it_user_service))
    before_admin = _snapshot(other_admin)
    before_super_admin = _snapshot(super_admin)

    body = {"description": "Should not stick."}
    to_admin = await it_client.patch(_profile_endpoint(other_admin.id_), json=body)
    to_super_admin = await it_client.patch(_profile_endpoint(super_admin.id_), json=body)

    assert to_admin.status_code == 403
    assert to_super_admin.status_code == 403
    await _assert_unchanged(it_session, other_admin, before_admin)
    await _assert_unchanged(it_session, super_admin, before_super_admin)


async def test_returns_404_for_an_unknown_user(
    it_client: httpx2.AsyncClient,
    it_admin: User,
) -> None:
    # The message too: until this route exists, every request to this path
    # answers a generic 404, so the status alone would pass by accident.
    r = await it_client.patch(_profile_endpoint(uuid4()), json={"description": "Nobody home."})

    assert r.status_code == 404
    assert r.json()["message"] == "User not found."


async def test_returns_409_and_changes_nothing_for_a_username_another_account_has(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_admin: User,
    it_user_service: UserService,
) -> None:
    other = create_user(it_user_service, raw_username="tony-stark")
    it_session.add(other)
    target = await _persist_target(it_session, create_user(it_user_service))
    before = _snapshot(target)

    r = await it_client.patch(_profile_endpoint(target.id_), json={"username": "tony-stark"})

    assert r.status_code == 409
    await _assert_unchanged(it_session, target, before)
