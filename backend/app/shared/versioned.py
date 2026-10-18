"""A write's result together with the aggregate version it committed."""

from dataclasses import dataclass
from datetime import datetime

from core_shared.etag import resource_etag


@dataclass(frozen=True)
class Versioned[T]:
    """What a write produced, and the aggregate version it left behind.

    For writes whose response does not re-read the whole aggregate - a field
    edit, a ``204`` delete - so the caller still learns which version to send
    as its next precondition. The version is captured inside the write's unit
    of work, under the aggregate's row lock: a read after the commit could
    already include somebody else's change, and a client handed that version
    would overwrite the change without ever having seen it.
    """

    value: T
    updated_at: datetime

    def etag(self, resource_type: str, resource_id: int) -> str | None:
        """The aggregate's entity-tag at the version this write committed."""
        return resource_etag(resource_type, resource_id, self.updated_at)
