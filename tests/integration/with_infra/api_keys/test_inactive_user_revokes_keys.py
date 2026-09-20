from typing import Any
from uuid import UUID

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.common.entities.api_key import ApiKey
from app.core.common.entities.types_ import UserRole
from app.core.common.services.user import UserService
from tests.integration.with_infra.authentication import authenticate
from tests.integration.with_infra.factories import create_raw_password, create_user_with_password
from tests.integration.with_infra.users.constants import USERS_ENDPOINT

# No /public prefix -- see conftest.py's own note on this.
API_KEYS_ENDPOINT = "/v1/api-keys/"


async def _issue_key(
    client: httpx2.AsyncClient,
    *,
    identifier: str,
    password: str,
) -> dict[str, Any]:
    response = await client.post(
        API_KEYS_ENDPOINT,
        json={"identifier": identifier, "password": password, "expires_in_days": 30, "label": None},
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


async def test_deactivating_a_user_via_the_private_app_revokes_all_their_api_keys(
    it_client: httpx2.AsyncClient,
    it_public_client: httpx2.AsyncClient,
    it_session: AsyncSession,
    it_user_service: UserService,
) -> None:
    """
    Pure end-to-end verification -- no new production code. Proves
    DeactivateUser (private app, unmodified) and ApiKeyIdentityProvider/
    CurrentUserService (public app, unmodified) compose correctly across
    process boundaries via nothing but the shared Postgres row.
    """
    # An admin, authenticated on the PRIVATE (cookie) app, to perform the
    # deactivation via the existing, unmodified DELETE .../activation/ route.
    admin_password = create_raw_password()
    admin = await create_user_with_password(it_user_service, raw_password=admin_password, role=UserRole.ADMIN)
    it_session.add(admin)
    await it_session.commit()
    await authenticate(it_client, admin.username.value, admin_password)

    # The target user issues TWO API keys via the public app.
    target_password = "correct-password1"
    target = await create_user_with_password(it_user_service, raw_password=target_password)
    it_session.add(target)
    await it_session.commit()
    key_a = await _issue_key(it_public_client, identifier=target.username.value, password=target_password)
    key_b = await _issue_key(it_public_client, identifier=target.username.value, password=target_password)

    response = await it_client.delete(f"{USERS_ENDPOINT}{target.id_}/activation/")
    assert response.status_code == 204

    # The first post-deactivation use of EITHER key is rejected immediately
    # -- CurrentUserService's own inactive-user guard rejects it before
    # ever consulting the api_keys table's own revoked_at column.
    follow_up_a = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": key_a["raw_key"]})
    assert follow_up_a.status_code == 401

    # That same request lazily revoked BOTH of the target's keys as a side
    # effect: CurrentUserService's inactive-user fallback calls
    # AccessRevoker.remove_all_user_access(), which in THIS container
    # (PublicApiProvider) resolves to ApiKeyAccessRevoker -- not just the
    # one key that happened to be used above. A direct DB check confirms
    # both rows now show revoked_at set, and the second, never-yet-used
    # key independently fails too.
    key_a_row = await it_session.get(ApiKey, UUID(key_a["id"]))
    key_b_row = await it_session.get(ApiKey, UUID(key_b["id"]))
    assert key_a_row is not None
    assert key_b_row is not None
    assert key_a_row.is_revoked
    assert key_b_row.is_revoked

    follow_up_b = await it_public_client.get(API_KEYS_ENDPOINT, headers={"X-API-Key": key_b["raw_key"]})
    assert follow_up_b.status_code == 401
