from inspect import getdoc
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.queries.list_api_keys import ApiKeySortingField, ListApiKeys, ListApiKeysRequest
from app.core.queries.ports.api_key_reader import ListApiKeysQm
from app.core.queries.query_support.exceptions import PaginationError
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME, ApiKeyAuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class ListApiKeysRequestSchema(BaseModel):
    """
    Using Pydantic model here is generally unnecessary.
    It's only implemented to render specific Swagger UI.
    """

    model_config = ConfigDict(frozen=True)

    limit: Annotated[int, Field(ge=1, le=OffsetPaginationParams.MAX_INT32)] = 20
    offset: Annotated[int, Field(ge=0, le=OffsetPaginationParams.MAX_INT32)] = 0
    sorting_field: Annotated[ApiKeySortingField, Field()] = ApiKeySortingField.CREATED_AT
    sorting_order: Annotated[SortingOrder, Field()] = SortingOrder.DESC


def make_list_api_keys_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/",
        error_map={
            # AuthorizationError maps to 401 here, NOT 403 like the private
            # app's list_users.py -- this query never calls authorize()
            # itself, so the only way it surfaces is CurrentUserService
            # finding the resolved key maps to a since-deleted/deactivated
            # account. That's "this credential no longer works" (401), not
            # "you're a real, active caller who lacks permission" (403).
            AuthorizationError: status.HTTP_401_UNAUTHORIZED,
            ApiKeyAuthenticationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            PaginationError: status.HTTP_400_BAD_REQUEST,
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
        },
        status_code=status.HTTP_200_OK,
        # Documentation-only -- see account/profile.py's identical
        # declaration for the full reasoning (ApiKeyIdentityProvider reads
        # X-API-Key straight off the raw Request, not through this).
        dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False))],
        description=getdoc(ListApiKeys),
    )
    @inject
    async def list_api_keys(
        request_schema: Annotated[ListApiKeysRequestSchema, Depends()],
        interactor: FromDishka[ListApiKeys],
    ) -> ListApiKeysQm:
        request = ListApiKeysRequest(
            limit=request_schema.limit,
            offset=request_schema.offset,
            sorting_field=request_schema.sorting_field,
            sorting_order=request_schema.sorting_order,
        )
        return await interactor.execute(request)

    return router
