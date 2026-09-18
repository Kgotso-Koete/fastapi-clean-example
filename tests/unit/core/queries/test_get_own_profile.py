import pytest

from app.core.queries.get_own_profile import GetOwnProfile
from app.core.queries.models.user import UserQm
from tests.unit.core.common.authorization.factories import create_current_user_service
from tests.unit.core.common.services.factories import create_super_user, create_user


def _expected_qm(user: object) -> UserQm:
    return UserQm(
        id=user.id_,  # type: ignore[attr-defined]
        username=user.username.value,  # type: ignore[attr-defined]
        email=user.email.value,  # type: ignore[attr-defined]
        phone_number=user.phone_number.value,  # type: ignore[attr-defined]
        role=user.role.value,  # type: ignore[attr-defined]
        is_active=user.is_active,  # type: ignore[attr-defined]
        created_at=user.created_at.value,  # type: ignore[attr-defined]
        updated_at=user.updated_at.value,  # type: ignore[attr-defined]
    )


@pytest.mark.asyncio
async def test_returns_the_current_users_own_profile() -> None:
    user = create_user()
    sut = GetOwnProfile(current_user_service=create_current_user_service(user))

    result = await sut.execute()

    assert result == _expected_qm(user)


@pytest.mark.asyncio
async def test_matches_whatever_user_it_resolves_to_not_a_hardcoded_shape() -> None:
    # A different role/entity than the test above, to prove the mapping
    # isn't accidentally hardcoded to one fixture's field values. Must
    # stay active -- CurrentUserService itself refuses to resolve an
    # inactive user at all, regardless of identity mechanism.
    user = create_super_user()
    sut = GetOwnProfile(current_user_service=create_current_user_service(user))

    result = await sut.execute()

    assert result == _expected_qm(user)
