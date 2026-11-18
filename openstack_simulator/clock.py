"""Virtual clock with an injectable source, a persistent offset and per-call override."""

import math
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Union

from .exceptions import InvalidTimestamp


class Clock:
    """Virtual-time clock.

    ``now()`` returns ``source() + offset``. ``advance()`` grows the persistent
    offset. A per-request ``override`` replaces the time returned by ``now()``
    but never alters the offset.
    """

    def __init__(self, source: Callable[[], float] = time.monotonic) -> None:
        self._source = source
        self._offset = 0.0

    def now(self, override: Optional[float] = None) -> float:
        if override is not None:
            return float(override)
        return self._source() + self._offset

    def advance(self, seconds: float) -> float:
        """Add ``seconds`` to the persistent offset and return the new time."""
        self._offset += float(seconds)
        return self.now()

    @staticmethod
    def parse(value: Union[str, int, float]) -> float:
        """Parse a float or ISO-8601 string into epoch seconds.

        Raises InvalidTimestamp (400) for anything else.
        """
        if isinstance(value, bool):
            raise InvalidTimestamp(f"Invalid timestamp: {value!r}")
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            text = value.strip()
            try:
                result = float(text)
            except ValueError:
                if text.endswith(("Z", "z")):
                    text = text[:-1] + "+00:00"
                try:
                    dt = datetime.fromisoformat(text)
                except ValueError:
                    raise InvalidTimestamp(f"Invalid timestamp: {value!r}") from None
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                result = dt.timestamp()
        else:
            raise InvalidTimestamp(f"Invalid timestamp: {value!r}")
        if not math.isfinite(result):
            raise InvalidTimestamp(f"Invalid timestamp: {value!r}")
        return result
