import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from app.core.commands.exceptions import UserNotFoundError
from app.core.commands.ports.flusher import Flusher
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.user_tx_storage import UserTxStorage
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.authorize import authorize
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.authorization.permissions import (
    CanManageRole,
    CanManageSubordinate,
    RoleManagementContext,
    UserManagementContext,
)
from app.core.common.entities.types_ import UserId, UserRole
from app.core.common.sentinels import OMITTED, Omitted, apply_when_present
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.username import Username

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateUserProfileRequest:
    user_id: UUID
    # OMITTED = left out, so unchanged (plan 15's sentinel); only the
    # description can also be None, which clears it
    # (docs/plans/10-profile-editing.md, decision 3).
    username: str | Omitted = OMITTED
    email: str | Omitted = OMITTED
    phone_number: str | Omitted = OMITTED
    description: str | Omitted | None = OMITTED


class UpdateUserProfileResponse(TypedDict):
    # The profile's fields. Its own type, like UpdateOrganizationResponse:
    # core commands may not import the query side's UserQm (import-linter's
    # CQRS contract).
    id: UUID
    username: str
    email: str
    phone_number: str
    role: str
    is_active: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


class UpdateUserProfile:
    """
    - Open to admins; edits another user's profile.
    - Admins can edit subordinate users only, as SetUserPassword.
    - No password needed: the role hierarchy is the authorization.
    - A partial update: a field left out stays as it is; null clears the description.
    - Every value is validated before anything changes.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        user_tx_storage: UserTxStorage,
        utc_timer: UtcTimer,
        flusher: Flusher,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_user_service = current_user_service
        self._user_tx_storage = user_tx_storage
        self._utc_timer = utc_timer
        self._flusher = flusher
        self._transaction_manager = transaction_manager

    async def execute(self, request: UpdateUserProfileRequest) -> UpdateUserProfileResponse:
        logger.info("Update user profile: started.")

        # 1. As SetUserPassword: only someone who manages USERs gets any
        #    further, so a plain USER is refused before anyone is looked up.
        current_user = await self._current_user_service.get_current_user()
        authorize(
            CanManageRole(),
            context=RoleManagementContext(
                subject=current_user,
                target_role=UserRole.USER,
            ),
        )

        # 2. Validate everything sent before changing anything (400).
        username = apply_when_present(Username, request.username)
        email = apply_when_present(Email, request.email)
        phone_number = apply_when_present(PhoneNumber, request.phone_number)
        description = apply_when_present(Description, request.description)

        # 3. The target; unknown is 404.
        user = await self._user_tx_storage.get_by_id(
            UserId(request.user_id),
            for_update=True,
        )
        if user is None:
            raise UserNotFoundError

        # 4. As SetUserPassword: only a subordinate of the caller, so an ADMIN
        #    can't edit another ADMIN or a SUPER_ADMIN.
        authorize(
            CanManageSubordinate(),
            context=UserManagementContext(
                subject=current_user,
                target=user,
            ),
        )

        # 5. Apply what was sent; updated_at moves only if something was.
        changed = False
        if not isinstance(username, Omitted):
            user.username = username
            changed = True
        if not isinstance(email, Omitted):
            user.email = email
            changed = True
        if not isinstance(phone_number, Omitted):
            user.phone_number = phone_number
            changed = True
        if not isinstance(description, Omitted):
            user.description = description
            changed = True
        if changed:
            user.updated_at = self._utc_timer.now

        # 6. Flush first, so a username/email/phone number another account
        #    already has surfaces from SqlaFlusher as *AlreadyExistsError
        #    (409); then commit.
        await self._flusher.flush()
        await self._transaction_manager.commit()

        logger.info("Update user profile: done.")
        return UpdateUserProfileResponse(
            id=user.id_,
            username=user.username.value,
            email=user.email.value,
            phone_number=user.phone_number.value,
            role=user.role.value,
            is_active=user.is_active,
            description=user.description.value if user.description is not None else None,
            created_at=user.created_at.value,
            updated_at=user.updated_at.value,
        )
