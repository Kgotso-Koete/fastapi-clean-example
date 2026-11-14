from typing import ClassVar

from app.base.core.common.exceptions import BaseError


class AuthorizationError(BaseError):
    default_message: ClassVar[str] = "Not authorized."
