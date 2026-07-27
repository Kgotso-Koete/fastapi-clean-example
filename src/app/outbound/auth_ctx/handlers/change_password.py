import logging
from dataclasses import dataclass

from app.core.commands.ports.transaction_manager import TransactionManager
from app.core.commands.ports.utc_timer import UtcTimer
from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.common.services.user import UserService
from app.core.common.value_objects.raw_password import RawPassword
from app.outbound.auth_ctx.exceptions import (
    AuthenticationChangeError,
    ReAuthenticationError,
)
from app.outbound.auth_ctx.service import AuthService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangePasswordRequest:
    current_password: str
    new_password: str


class ChangePassword:
    """
    - Open to authenticated users.
    - Current user can change their password.
    - New password must differ from current password.
    - Automatically revokes all existing sessions to secure the account.
    """

    def __init__(
        self,
        current_user_service: CurrentUserService,
        user_service: UserService,
        utc_timer: UtcTimer,
        transaction_manager: TransactionManager,
        auth_service: AuthService,
    ) -> None:
        self._current_user_service = current_user_service
        self._user_service = user_service
        self._utc_timer = utc_timer
        self._transaction_manager = transaction_manager
        self._auth_service = auth_service

    async def execute(self, request: ChangePasswordRequest) -> None:
        logger.info("Change password: started.")

        current_user = await self._current_user_service.get_current_user(for_update=True)
        current_password = RawPassword(request.current_password)
        new_password = RawPassword(request.new_password)
        if current_password == new_password:
            raise AuthenticationChangeError

        if not await self._user_service.is_password_valid(current_user, current_password):
            raise ReAuthenticationError

        await self._user_service.change_password(
            current_user,
            new_password,
            now=self._utc_timer.now,
        )
        await self._transaction_manager.commit()

        # Security: Invalidate the current cookie and wipe all sessions from the database
        await self._auth_service.logout_current_session()
        await self._auth_service.revoke_all_sessions(current_user.id_)

        logger.info("Change password: done.")
