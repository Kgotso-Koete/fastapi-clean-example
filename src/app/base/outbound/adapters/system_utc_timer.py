from datetime import UTC, datetime

from app.base.core.commands.ports.utc_timer import UtcTimer
from app.base.core.common.value_objects.utc_datetime import UtcDatetime


class SystemUtcTimer(UtcTimer):
    @property
    def now(self) -> UtcDatetime:
        return UtcDatetime(datetime.now(UTC))
