import logging

logger = logging.getLogger(__name__)


def log_info(err: Exception) -> None:
    # Called for every error a route maps to a status code. When the error was
    # raised `from` another one (a 503 StorageError from a database failure,
    # say), the cause is named too, so the log says what really went wrong
    # (docs/plans/15-upstream-autumn-2026.md, Step 3, after the original
    # author's change). Only the cause's TYPE is logged, never its message:
    # a database error's message carries SQL parameters and Postgres DETAIL
    # lines (emails, phone numbers, password hashes), which OWASP's Logging
    # Cheat Sheet says not to log. The type alone tells a connection failure
    # (OperationalError) from a constraint clash (IntegrityError).
    cause = err.__cause__
    if cause is None:
        logger.info("Handled exception: %s — %s", type(err).__name__, err)
    else:
        logger.info(
            "Handled exception: %s — %s; caused by: %s",
            type(err).__name__,
            err,
            type(cause).__name__,
        )
