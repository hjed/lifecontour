"""Unit tests for AlbumSyncReadRepository reference_data decoding.

A corrupted ``external_references.reference_data`` value must not break
PHOTO_ALBUM journal reads — decoding tolerates bad JSON and non-object shapes.
"""

from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)


class TestDecodeReferenceData:
    def test_none_or_empty_returns_empty_dict(self) -> None:
        assert AlbumSyncReadRepository._decode_reference_data(None, 1) == {}
        assert AlbumSyncReadRepository._decode_reference_data("", 1) == {}

    def test_valid_json_object_is_returned(self) -> None:
        result = AlbumSyncReadRepository._decode_reference_data(
            '{"album_name": "Trip", "asset_count": 3}', 1
        )
        assert result == {"album_name": "Trip", "asset_count": 3}

    def test_malformed_json_returns_empty_dict(self) -> None:
        assert AlbumSyncReadRepository._decode_reference_data("{not json", 1) == {}

    def test_non_object_json_returns_empty_dict(self) -> None:
        # Valid JSON but not an object (e.g. a list or string).
        assert AlbumSyncReadRepository._decode_reference_data('["a", "b"]', 1) == {}
        assert (
            AlbumSyncReadRepository._decode_reference_data('"just a string"', 1) == {}
        )
