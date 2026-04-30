"""Backward-compatible re-export of StreamConsumer from core_shared.

The StreamConsumer base class was moved to core_shared to enable
integration workers (e.g. Google worker) to use it directly.
Backend consumers continue to import from this location.
"""

from core_shared.stream_consumer import StreamConsumer

__all__ = ["StreamConsumer"]
