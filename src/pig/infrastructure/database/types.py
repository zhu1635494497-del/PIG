from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Store timezone-aware instants as normalized UTC ISO-8601 text.

    SQLite has no native timezone-aware datetime type. A text representation also
    keeps migration and cross-platform behavior deterministic.
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(
        self, value: Optional[datetime], dialect: Dialect
    ) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

    def process_result_value(
        self, value: Optional[str], dialect: Dialect
    ) -> Optional[datetime]:
        if value is None:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )

    @property
    def python_type(self) -> type[datetime]:
        return datetime
