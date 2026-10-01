from inspect import getdoc
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from starlette import status

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.queries.list_my_organizations import (
    ListMyOrganizations,
    ListMyOrganizationsRequest,
    OrganizationSortingField,
)
from app.core.queries.ports.organization_reader import ListMyOrganizationsQm
from app.core.queries.query_support.exceptions import PaginationError
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class ListMyOrganizationsRequestSchema(BaseModel):
    """Query parameters, as a Pydantic model only to render them in Swagger UI
    (the same reason as ListApiKeysRequestSchema)."""

    model_config = ConfigDict(frozen=True)

    limit: Annotated[int, Field(ge=1, le=OffsetPaginationParams.MAX_INT32)] = 20
    offset: Annotated[int, Field(ge=0, le=OffsetPaginationParams.MAX_INT32)] = 0
    sorting_field: Annotated[OrganizationSortingField, Field()] = OrganizationSortingField.CREATED_AT
    sorting_order: Annotated[SortingOrder, Field()] = SortingOrder.DESC


def make_list_my_organizations_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            # An unknown/inactive caller (CurrentUserService).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            PaginationError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_200_OK,
        description=getdoc(ListMyOrganizations),
    )
    @inject
    async def list_my_organizations(
        request_schema: Annotated[ListMyOrganizationsRequestSchema, Depends()],
        interactor: FromDishka[ListMyOrganizations],
    ) -> ListMyOrganizationsQm:
        request = ListMyOrganizationsRequest(
            limit=request_schema.limit,
            offset=request_schema.offset,
            sorting_field=request_schema.sorting_field,
            sorting_order=request_schema.sorting_order,
        )
        return await interactor.execute(request)

    return router
