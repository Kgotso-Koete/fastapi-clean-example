import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from app.core.commands.ports.organization_repository import OrganizationRepository
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.entities.organization import Organization
from app.core.common.entities.organization_membership import OrganizationMembership, OrganizationRole
from app.core.common.factories.organization_id_factory import create_organization_id
from app.core.common.factories.organization_membership_id_factory import create_organization_membership_id
from app.core.common.value_objects.organization_name import OrganizationName

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateOrganizationRequest:
    name: str


class CreateOrganizationResponse(TypedDict):
    id: UUID
    name: str
    created_at: datetime


class CreateOrganization:
    """
    - Open to any authenticated caller.
    - Creates an organization, and makes the caller its OWNER -- an
      already-accepted membership, so the creator needs no self-invite.
    - Both rows are staged before a single commit: one transaction, so an
      organization can never exist without its first owner.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        organization_repository: OrganizationRepository,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_user_service = current_user_service
        self._organization_repository = organization_repository
        self._utc_timer = utc_timer
        self._transaction_manager = transaction_manager

    async def execute(self, request: CreateOrganizationRequest) -> CreateOrganizationResponse:
        logger.info("Create organization: started.")

        # Who is calling first -- an unknown/inactive caller raises
        # AuthorizationError here, before anything else happens.
        current_user = await self._current_user_service.get_current_user()
        # Validated (and trimmed) BEFORE anything is staged -- an invalid
        # name raises BusinessTypeError and leaves no partial write.
        name = OrganizationName(request.name)
        now = self._utc_timer.now

        organization = Organization(
            id_=create_organization_id(),
            name=name,
            created_by_user_id=current_user.id_,
            created_at=now,
        )
        owner_membership = OrganizationMembership(
            id_=create_organization_membership_id(),
            organization_id=organization.id_,
            user_id=current_user.id_,
            role=OrganizationRole.OWNER,
            # The creator "invites" themselves, and is accepted from the
            # moment the organization exists.
            invited_by_user_id=current_user.id_,
            created_at=now,
            accepted_at=now,
            # Accepted, so it never expires -- stated explicitly, since the
            # entity requires every caller to decide (see its invariant).
            expires_at=None,
        )
        self._organization_repository.add(organization)
        self._organization_repository.add_membership(owner_membership)
        await self._transaction_manager.commit()

        logger.info("Create organization: done.")
        return CreateOrganizationResponse(
            id=organization.id_,
            name=organization.name.value,
            created_at=now.value,
        )
