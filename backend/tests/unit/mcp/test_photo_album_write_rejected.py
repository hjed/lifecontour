"""PHOTO_ALBUM type data is integration-managed and rejected on MCP writes.

Mirrors the REST API fail-fast behaviour so an MCP caller cannot believe an
update succeeded when nothing was persisted.
"""

from unittest.mock import MagicMock

import pytest
from core_shared.models.journals import JournalType, JournalValidationError

from app.mcp.domains.journals.tools import _update_type_specific_data


async def test_update_photo_album_type_data_is_rejected() -> None:
    # The PHOTO_ALBUM branch raises before touching any repository, so mocks are
    # sufficient for the 15 repository parameters. A JournalValidationError (a
    # JournalDomainError) is raised so the MCP error handler returns a clear
    # validation message rather than a generic internal error.
    repos = [MagicMock() for _ in range(15)]

    with pytest.raises(JournalValidationError, match="managed by Immich"):
        await _update_type_specific_data(
            JournalType.PHOTO_ALBUM,
            1,
            {"immich_album_id": "album-123"},
            *repos,
        )
