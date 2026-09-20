from typing import ClassVar, Final

from app.core.common.exceptions import BaseError

# A distinct message from the credentials-wrong case, deliberately -- "your
# account is inactive" isn't a username-enumeration risk the way "no such
# user" vs. "wrong password" is: there's no ambiguity left to hide once the
# caller already proved they know the correct password.
API_KEY_ACCOUNT_INACTIVE: Final[str] = "Your account is inactive. Please contact support."


class InvalidApiKeyCredentialsError(BaseError):
    """
    Raised for both an unknown username and a wrong password, with the same
    default message -- a different message per case would let a caller
    enumerate valid usernames by watching which message they get back.
    Not added to the existing core/commands/exceptions.py -- this file is
    specific to the public API's own credential-verification step
    (IssueApiKey), mirroring how ApiKeyAuthenticationError/CliIdentityError
    each live in their own self-contained file rather than a shared one.
    """

    default_message: ClassVar[str] = "Invalid username or password."


class ApiKeyNotFoundError(BaseError):
    """Raised by RevokeApiKey (and GetApiKeyUsageStats) for an unknown
    api_key_id -- kept here rather than core/commands/exceptions.py for
    the same reason InvalidApiKeyCredentialsError is: this file is
    specific to the public API's own ApiKey-by-id commands/queries."""

    default_message: ClassVar[str] = "API key not found."


class ApiKeyLimitExceededError(BaseError):
    """Raised by IssueApiKey when the caller already has the maximum
    allowed number of active (non-revoked) API keys. Revoking an existing
    key frees up a slot -- the limit is on active keys, not a lifetime cap."""

    default_message: ClassVar[str] = "You have reached the maximum number of active API keys."
