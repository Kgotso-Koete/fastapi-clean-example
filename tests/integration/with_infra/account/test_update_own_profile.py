import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.user import User
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from tests.integration.with_infra.account.constants import LOG_IN_ENDPOINT, LOG_OUT_ENDPOINT, PROFILE_ENDPOINT
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_raw_password, create_user, create_user_with_password

# PATCH /api/v1/account/profile/ (docs/plans/10-profile-editing.md, Step 6):
# a logged-in user edits their own username, email, phone number and
# description, through UpdateOwnProfile. Every refusal re-reads the user and
# checks nothing changed, not just the status code.


async def _log_in(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> tuple[User, str]:
    """A new user with a description, logged in. Returns them and their password."""
    password = create_raw_password()
    user = await create_user_with_password(it_user_service, raw_password=password)
    user.description = Description("Friendly neighborhood photographer.")
    it_session.add(user)
    await it_session.commit()
    await authenticate(it_client, user.username.value, password)
    return user, password


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


async def test_returns_200_and_changes_every_field_sent(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user, password = await _log_in(it_client, it_session, it_user_service)

    r = await it_client.patch(
        PROFILE_ENDPOINT,
        json={
            "username": "spider-man",
            "email": "spidey@example.com",
            "phone_number": "0821000099",
            "description": "Your friendly neighborhood Spider-Man.",
            "current_password": password,
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "spider-man"
    assert body["email"] == "spidey@example.com"
    assert body["phone_number"] == "27821000099"
    assert body["description"] == "Your friendly neighborhood Spider-Man."
    await it_session.refresh(user)
    assert _snapshot(user) == (
        "spider-man",
        "spidey@example.com",
        "27821000099",
        "Your friendly neighborhood Spider-Man.",
    )


async def test_returns_200_and_leaves_fields_not_sent_unchanged(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user, _ = await _log_in(it_client, it_session, it_user_service)
    before = _snapshot(user)

    r = await it_client.patch(PROFILE_ENDPOINT, json={"phone_number": "0821000099"})

    assert r.status_code == 200
    await it_session.refresh(user)
    assert _snapshot(user) == (before[0], before[1], "27821000099", before[3])


async def test_returns_200_and_null_clears_the_description(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    user, _ = await _log_in(it_client, it_session, it_user_service)

    r = await it_client.patch(PROFILE_ENDPOINT, json={"description": None})

    assert r.status_code == 200
    assert r.json()["description"] is None
    await it_session.refresh(user)
    assert user.description is None


async def test_returns_400_and_changes_nothing_for_a_blank_description(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A valid username sent alongside: it must not be applied either.
    user, _ = await _log_in(it_client, it_session, it_user_service)
    before = _snapshot(user)

    r = await it_client.patch(PROFILE_ENDPOINT, json={"username": "spider-man", "description": "   "})

    assert r.status_code == 400
    await _assert_unchanged(it_session, user, before)


async def test_returns_401_when_not_authenticated(
    it_client: httpx2.AsyncClient,
) -> None:
    r = await it_client.patch(PROFILE_ENDPOINT, json={"description": "Hello"})

    assert r.status_code == 401


async def test_returns_403_and_changes_nothing_for_a_new_email_without_the_right_password(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Decision 2: missing and wrong are the same refused re-authentication,
    # answered as PUT /account/password/ answers.
    user, _ = await _log_in(it_client, it_session, it_user_service)
    before = _snapshot(user)

    missing = await it_client.patch(PROFILE_ENDPOINT, json={"email": "spidey@example.com"})
    wrong = await it_client.patch(
        PROFILE_ENDPOINT,
        json={"email": "spidey@example.com", "current_password": "NotMyPassword123!"},
    )

    assert missing.status_code == 403
    assert missing.json()["message"] == "Invalid password."
    assert wrong.status_code == 403
    assert wrong.json()["message"] == "Invalid password."
    await _assert_unchanged(it_session, user, before)


async def test_returns_200_and_only_the_new_email_logs_in_after_a_change(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # Proves the change reached the login path, not just the profile.
    user, password = await _log_in(it_client, it_session, it_user_service)
    old_email = user.email.value

    r = await it_client.patch(PROFILE_ENDPOINT, json={"email": "spidey@example.com", "current_password": password})

    assert r.status_code == 200
    assert (await it_client.delete(LOG_OUT_ENDPOINT)).status_code == 204
    old = await it_client.post(LOG_IN_ENDPOINT, json={"identifier": old_email, "password": password})
    assert old.status_code == 401
    new = await it_client.post(LOG_IN_ENDPOINT, json={"identifier": "spidey@example.com", "password": password})
    assert new.status_code == 200


async def test_returns_409_and_changes_nothing_for_a_username_another_account_has(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    other = create_user(it_user_service, raw_username="tony-stark")
    it_session.add(other)
    await it_session.commit()
    user, _ = await _log_in(it_client, it_session, it_user_service)
    before = _snapshot(user)

    r = await it_client.patch(PROFILE_ENDPOINT, json={"username": "tony-stark"})

    assert r.status_code == 409
    await _assert_unchanged(it_session, user, before)


async def test_returns_422_for_a_malformed_body(
    it_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    # A number where text belongs: the body itself is malformed, so it's
    # refused before any domain rule is checked.
    user, _ = await _log_in(it_client, it_session, it_user_service)
    before = _snapshot(user)

    r = await it_client.patch(PROFILE_ENDPOINT, json={"description": 123})

    assert r.status_code == 422
    await _assert_unchanged(it_session, user, before)
