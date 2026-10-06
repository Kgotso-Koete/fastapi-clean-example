from inspect import getdoc
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Path, status
from fastapi.security import APIKeyHeader

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.common.authorization.organization_exceptions import OrganizationNotFoundError
from app.core.queries.list_organization_members import ListOrganizationMembers, ListOrganizationMembersRequest
from app.core.queries.ports.organization_reader import ListOrganizationMembersQm
from app.core.queries.query_support.exceptions import PaginationError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE

# Reused from the cookie route, not copied -- see this package's
# list_my_organizations.py for why.
from app.inbound.http.organizations.list_organization_members import ListOrganizationMembersRequestSchema
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME, ApiKeyAuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


def make_list_organization_members_router() -> APIRouter:
    # The public twin of inbound/http/organizations/list_organization_members.py
    # (docs/plans/9-organizations.md, Step 15): the same ListOrganizationMembers
    # query, with the caller identified by X-API-Key instead of a cookie.
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/{organization_id}/members/",
        error_map={
            # No key, or an unknown, revoked or expired one.
            ApiKeyAuthenticationError: status.HTTP_401_UNAUTHORIZED,
            # 401, not the cookie route's 403. Listing members needs only
            # MEMBER, the lowest role, so CurrentOrganizationService can never
            # refuse a member for their role here. The only source left is
            # CurrentUserService finding the key's account deactivated: "this
            # credential no longer works" (as in public_api/api_keys/list_api_keys.py).
            AuthorizationError: status.HTTP_401_UNAUTHORIZED,
            # Not a member at all -- the organization's existence isn't
            # revealed, exactly as on the cookie route.
            OrganizationNotFoundError: status.HTTP_404_NOT_FOUND,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            PaginationError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_200_OK,
        # Documentation-only -- see public_api/account/profile.py for why.
        dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False))],
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
