from typing import ClassVar

from app.core.common.exceptions import BaseError


class UsernameAlreadyExistsError(BaseError):
    default_message: ClassVar[str] = "Username already exists."


class UserNotFoundError(BaseError):
    default_message: ClassVar[str] = "User not found."


class EmailAlreadyExistsError(BaseError):
    default_message: ClassVar[str] = "Email already exists."


class PhoneNumberAlreadyExistsError(BaseError):
    default_message: ClassVar[str] = "Phone number already exists."
