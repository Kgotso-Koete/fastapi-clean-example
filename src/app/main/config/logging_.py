import logging
from enum import StrEnum
from typing import ClassVar, Final

# fmt: off
FMT: Final[str] = (
    "\n[%(asctime)s.%(msecs)03d] [%(threadName)s] "
    "%(funcName)20s "
    "%(module)s:%(lineno)d \n"
    "%(levelname)s - %(message)s"
)
# fmt: on
DATEFMT: Final[str] = "%Y-%m-%d %H:%M:%S"


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
