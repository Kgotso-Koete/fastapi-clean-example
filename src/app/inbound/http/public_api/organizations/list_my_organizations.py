from inspect import getdoc
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, status
from fastapi.security import APIKeyHeader

from app.core.common.authorization.exceptions import AuthorizationError
from app.core.queries.list_my_organizations import ListMyOrganizations, ListMyOrganizationsRequest
from app.core.queries.ports.organization_reader import ListMyOrganizationsQm
from app.core.queries.query_support.exceptions import PaginationError
from app.inbound.http.errors.callbacks import log_info
from app.inbound.http.errors.router import make_error_aware_router
from app.inbound.http.errors.rules import HTTP_503_SERVICE_UNAVAILABLE_RULE

# Reused from the cookie route, not copied: its defaults (page size, sort
# field and order) are part of what makes both entrypoints return the same
# JSON, so there is exactly one definition of them.
from app.inbound.http.organizations.list_my_organizations import ListMyOrganizationsRequestSchema
from app.outbound.adapters.api_key_identity_provider import API_KEY_HEADER_NAME, ApiKeyAuthenticationError
from app.outbound.exceptions import ReaderError, StorageError


def make_list_my_organizations_router() -> APIRouter:
    # The public twin of inbound/http/organizations/list_my_organizations.py
    # (docs/plans/9-organizations.md, Step 15): the same ListMyOrganizations
    # query, with the caller identified by X-API-Key instead of a cookie.
    router = make_error_aware_router(on_error=log_info)

    @router.get(
        "/",
        error_map={
            # No key, or an unknown, revoked or expired one.
            ApiKeyAuthenticationError: status.HTTP_401_UNAUTHORIZED,
            # 401 here, not the cookie route's 403, for the same reason as
            # public_api/api_keys/list_api_keys.py: this query never calls
            # authorize() itself, so the only source is CurrentUserService
            # finding the key's account deactivated -- "this credential no
            # longer works", not "you lack permission".
            AuthorizationError: status.HTTP_401_UNAUTHORIZED,
            StorageError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            ReaderError: HTTP_503_SERVICE_UNAVAILABLE_RULE,
            PaginationError: status.HTTP_400_BAD_REQUEST,
        },
        status_code=status.HTTP_200_OK,
        # Documentation-only -- see public_api/account/profile.py for why.
        dependencies=[Depends(APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False))],
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
