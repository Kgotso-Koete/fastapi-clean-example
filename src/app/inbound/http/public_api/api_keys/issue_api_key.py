from inspect import getdoc
from typing import Annotated, Any, Final

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, status

from app.core.commands.api_key_exceptions import ApiKeyLimitExceededError, InvalidApiKeyCredentialsError
from app.core.commands.issue_api_key import IssueApiKey, IssueApiKeyRequest, IssueApiKeyResponse
from app.core.common.exceptions import BusinessTypeError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.exceptions import StorageError

# Sample request body shown in Swagger (/docs), which developers copy. The
# schema only says "string" and "integer", so the values are chosen by hand to
# pass core's rules (expires_in_days 1-365); the credentials are the seeded
# peter-parker's (scripts/seed_db.py), and tests/sanity/inbound/http/ checks
# the fields against the schema (docs/plans/15-upstream-autumn-2026.md,
# Step 5, item 10).
ISSUE_API_KEY_EXAMPLES: Final[dict[str, Any]] = {
    "thirty_day_key": {
        "summary": "Issue a key that expires in 30 days",
        "value": {
            "identifier": "peter-parker",
            "password": "SpideySense2024!",
            "expires_in_days": 30,
            "label": "Spider-Sense Dev Key",
        },
    },
}


def make_issue_api_key_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.post(
        "/",
        # No auth dependency on this route, unlike list/revoke -- this is
        # the "open, prove who you are via the request body" route, exactly
        # like POST /account/login/. See the plan's router-group note.
        error_map={
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            BusinessTypeError: status.HTTP_400_BAD_REQUEST,
            InvalidApiKeyCredentialsError: status.HTTP_401_UNAUTHORIZED,
            ApiKeyLimitExceededError: status.HTTP_409_CONFLICT,
        },
        status_code=status.HTTP_201_CREATED,
        description=getdoc(IssueApiKey),
    )
    @inject
    async def issue_api_key(
        request: Annotated[IssueApiKeyRequest, Body(openapi_examples=ISSUE_API_KEY_EXAMPLES)],
        handler: FromDishka[IssueApiKey],
    ) -> IssueApiKeyResponse:
        return await handler.execute(request)

    return router
