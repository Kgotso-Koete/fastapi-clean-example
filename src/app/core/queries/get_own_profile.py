import logging

from app.core.common.authorization.current_user_service import CurrentUserService
from app.core.queries.models.user import UserQm

logger = logging.getLogger(__name__)


class GetOwnProfile:
    """
    - Open to any authenticated caller, via whichever IdentityProvider the
      container has -- cookie session (CoreProvider) or API key
      (PublicApiProvider).
    - Self-service: returns the caller's OWN profile only.
    - No authorize() call -- viewing your own profile needs nothing beyond
      being an authenticated, active user.
    - Bound unmodified into BOTH CoreProvider and PublicApiProvider -- the
      concrete proof that CurrentUserService abstracts over the identity
      mechanism: same class, same logic, two transports.
    """

    def __init__(self, current_user_service: CurrentUserService) -> None:
        self._current_user_service = current_user_service

    async def execute(self) -> UserQm:
        logger.info("Get own profile: started.")

        current_user = await self._current_user_service.get_current_user()

        logger.info("Get own profile: done.")
        return UserQm(
            id=current_user.id_,
            username=current_user.username.value,
            email=current_user.email.value,
            phone_number=current_user.phone_number.value,
            role=current_user.role.value,
            is_active=current_user.is_active,
            created_at=current_user.created_at.value,
            updated_at=current_user.updated_at.value,
        )
