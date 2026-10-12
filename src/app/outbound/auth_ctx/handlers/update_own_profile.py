import logging
from dataclasses import dataclass

from app.core.commands.ports.flusher import Flusher
from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.entities.user import User
from app.core.common.sentinels import OMITTED, Omitted, apply_when_present
from app.core.common.services.user import UserService
from app.core.common.value_objects.description import Description
from app.core.common.value_objects.email import Email
from app.core.common.value_objects.phone_number import PhoneNumber
from app.core.common.value_objects.raw_password import RawPassword
from app.core.common.value_objects.username import Username
from app.core.queries.models.user import UserQm
from app.outbound.auth_ctx.exceptions import ReAuthenticationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateOwnProfileRequest:
    # OMITTED = left out, so unchanged (plan 15's sentinel); only the
    # description can also be None, which clears it
    # (docs/plans/10-profile-editing.md, decision 3).
    username: str | Omitted = OMITTED
    email: str | Omitted = OMITTED
    phone_number: str | Omitted = OMITTED
    description: str | Omitted | None = OMITTED
    current_password: str | None = None


class UpdateOwnProfile:
    """
    - Open to any logged-in user; edits only the caller, never an id from the path.
    - A partial update: a field left out stays as it is; null clears the description.
    - Every value is validated before anything changes.
    - Changing the email needs the current password, like ChangePassword.
    - A username, email or phone number another account has is a 409.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        user_service: UserService,
        utc_timer: UtcTimer,
        flusher: Flusher,
        transaction_manager: TransactionManager,
    ) -> None:
        self._current_user_service = current_user_service
        self._user_service = user_service
        self._utc_timer = utc_timer
        self._flusher = flusher
        self._transaction_manager = transaction_manager

    async def execute(self, request: UpdateOwnProfileRequest) -> UserQm:
        logger.info("Update own profile: started.")

        current_user = await self._current_user_service.get_current_user(for_update=True)

        # 1. Validate everything sent before changing anything (400), so an
        #    invalid field never leaves a half-applied update behind.
        username = apply_when_present(Username, request.username)
        email = apply_when_present(Email, request.email)
        phone_number = apply_when_present(PhoneNumber, request.phone_number)
        description = apply_when_present(Description, request.description)

        # 2. A CHANGED email needs the right current password (decision 2;
        #    OWASP: re-authenticate before changing a login identifier).
        #    Missing or wrong are both ReAuthenticationError (403), as in
        #    ChangePassword. Re-sending the same email needs none.
        if not isinstance(email, Omitted) and email != current_user.email:
            await self._reauthenticate(current_user, request.current_password)

        # 3. Apply what was sent; updated_at moves only if something was.
        changed = False
        if not isinstance(username, Omitted):
            current_user.username = username
            changed = True
        if not isinstance(email, Omitted):
            current_user.email = email
            changed = True
        if not isinstance(phone_number, Omitted):
            current_user.phone_number = phone_number
            changed = True
        if not isinstance(description, Omitted):
            current_user.description = description
            changed = True
        if changed:
            current_user.updated_at = self._utc_timer.now

        # 4. Flush first, so a username/email/phone number another account
        #    already has surfaces from SqlaFlusher as *AlreadyExistsError
        #    (409), the same path SignUp relies on; then commit.
        await self._flusher.flush()
        await self._transaction_manager.commit()

        logger.info("Update own profile: done.")
        return UserQm(
            id=current_user.id_,
            username=current_user.username.value,
            email=current_user.email.value,
            phone_number=current_user.phone_number.value,
            role=current_user.role.value,
            is_active=current_user.is_active,
            created_at=current_user.created_at.value,
            updated_at=current_user.updated_at.value,
            description=current_user.description.value if current_user.description is not None else None,
        )

    async def _reauthenticate(self, user: User, current_password: str | None) -> None:
        if current_password is None:
            raise ReAuthenticationError
        # RawPassword raises 400 for a malformed password, as in ChangePassword.
        if not await self._user_service.is_password_valid(user, RawPassword(current_password)):
            raise ReAuthenticationError
