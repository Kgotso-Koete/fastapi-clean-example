from fastapi import APIRouter

from app.inbound.http.public_api.api_keys.get_api_key_usage_stats import make_get_api_key_usage_stats_router
from app.inbound.http.public_api.api_keys.issue_api_key import make_issue_api_key_router
from app.inbound.http.public_api.api_keys.list_api_keys import make_list_api_keys_router
from app.inbound.http.public_api.api_keys.revoke_api_key import make_revoke_api_key_router


def make_api_keys_router() -> APIRouter:
    router = APIRouter(prefix="/api-keys", tags=["API Keys"])
    router.include_router(make_issue_api_key_router())
    router.include_router(make_list_api_keys_router())
    router.include_router(make_revoke_api_key_router())
    router.include_router(make_get_api_key_usage_stats_router())
    return router
