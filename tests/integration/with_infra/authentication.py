import httpx2

from tests.integration.with_infra.account.constants import LOG_IN_ENDPOINT


async def authenticate(client: httpx2.AsyncClient, username: str, password: str) -> None:
    r = await client.post(LOG_IN_ENDPOINT, json={"identifier": username, "password": password})
    assert r.status_code == 200
