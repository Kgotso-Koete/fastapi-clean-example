from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field
from starlette import status

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.queries.list_organization_members import (
    ListOrganizationMembers,
    ListOrganizationMembersRequest,
    MemberSortingField,
)
from app.core.queries.ports.organization_reader import ListOrganizationMembersQm
from app.core.queries.query_support.exceptions import PaginationError
from app.core.queries.query_support.offset_pagination import OffsetPaginationParams
from app.core.queries.query_support.sorting import SortingOrder
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE
from app.outbound.auth_ctx.exceptions import AuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


class ListOrganizationMembersRequestSchema(BaseModel):
    """Query parameters, as a Pydantic model only to render them in Swagger UI.
    Oldest first by default, so the founding owner leads the list."""

    model_config = ConfigDict(frozen=True)

    limit: Annotated[int, Field(ge=1, le=OffsetPaginationParams.MAX_INT32)] = 20
    offset: Annotated[int, Field(ge=0, le=OffsetPaginationParams.MAX_INT32)] = 0
    sorting_field: Annotated[MemberSortingField, Field()] = MemberSortingField.CREATED_AT
    sorting_order: Annotated[SortingOrder, Field()] = SortingOrder.ASC


def make_list_organization_members_router() -> APIRouter:
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/{organization_id}/members/",
        error_map={
            AuthenticationError: status.HTTP_401_UNAUTHORIZED,
            # An unknown/inactive caller (CurrentUserService).
            AuthorizationError: status.HTTP_403_FORBIDDEN,
            # Not a member at all -- the organization's existence isn't revealed.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            PaginationError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_200_OK,
        description=getdoc(ListOrganizationMembers),
    )
    @inject
    async def list_organization_members(
        organization_id: Annotated[UUID, Path()],
        request_schema: Annotated[ListOrganizationMembersRequestSchema, Depends()],
        interactor: FromDishka[ListOrganizationMembers],
    ) -> ListOrganizationMembersQm:
        request = ListOrganizationMembersRequest(
            organization_id=organization_id,
            limit=request_schema.limit,
            offset=request_schema.offset,
            sorting_field=request_schema.sorting_field,
            sorting_order=request_schema.sorting_order,
        )
        return await interactor.execute(request)

    return router
