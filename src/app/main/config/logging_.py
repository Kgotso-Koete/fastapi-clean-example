import json
import logging
from enum import StrEnum
from typing import Any, ClassVar, Final

# fmt: off
FMT: Final[str] = (
    "\n[%(asctime)s.%(msecs)03d] [%(threadName)s] "
    "%(funcName)20s "
    "%(module)s:%(lineno)d \n"
    "%(levelname)s - %(message)s"
)
# fmt: on
DATEFMT: Final[str] = "%Y-%m-%d %H:%M:%S"

# vvv NEW vvv
# Attributes every stdlib LogRecord carries. Anything else found on a record
# was passed in via `extra={...}` at the call site and should be surfaced as
# its own field in structured output, e.g. `logger.error(..., extra={"exception_type": "ValueError"})`.
_STANDARD_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
    }
)


class LoggingLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class HumanReadableFormatter(logging.Formatter):
    """Adds emojis, ANSI colors, and vertical spacing to logs."""

    EMOJIS: ClassVar[dict[int, str]] = {
        logging.DEBUG: "🐛",
        logging.INFO: "ℹ️",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "🚨",
    }

    COLORS: ClassVar[dict[int, str]] = {
        logging.DEBUG: "\033[90m",  # Gray
        logging.INFO: "\033[94m",  # Blue
        logging.WARNING: "\033[93m",  # Yellow
        logging.ERROR: "\033[91m",  # Red
        logging.CRITICAL: "\033[1;91m",  # Bold Red
    }
    RESET: ClassVar[str] = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        # Save original attributes we are going to mutate
        original_levelname = record.levelname

        emoji = self.EMOJIS.get(record.levelno, "")
        color = self.COLORS.get(record.levelno, self.RESET)

        # Inject color and emoji into the level name
        # We manually pad the original name to 8 chars because ANSI codes break standard %-8s formatting
        record.levelname = f"{color}{emoji} {original_levelname:<8}{self.RESET}"

        # Format the full message using the standard formatter
        result = super().format(record)

        # Restore the original attributes to not break downstream handlers
        record.levelname = original_levelname

        return result


# vvv ENTIRE CLASS BELOW IS NEW vvv
class JsonFormatter(logging.Formatter):
    """
    One JSON object per line, so a log shipper (e.g. Promtail) can parse and
    index fields for filtering/search — by level, logger name, exception type,
    request path, etc. — instead of grepping free-text.

    Any `extra={...}` passed to a logging call is merged in as its own
    top-level field, e.g.:
        logger.error("Unhandled exception", extra={"exception_type": "ValueError", "path": "/v1/users"})
    becomes:
        {"...", "exception_type": "ValueError", "path": "/v1/users"}
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, DATEFMT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "thread": record.threadName,
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extra = {key: value for key, value in record.__dict__.items() if key not in _STANDARD_RECORD_ATTRS}
        payload.update(extra)

        return json.dumps(payload, default=str)
