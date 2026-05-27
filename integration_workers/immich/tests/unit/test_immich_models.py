"""Unit tests for Immich Pydantic response models.

Validates that models correctly parse camelCase JSON from the Immich API
and handle optional/nullable fields gracefully.
"""

from typing import Any

import pytest

from immich_models import (
    ImmichAlbum,
    ImmichAsset,
    ImmichPeopleResponse,
    ImmichPerson,
    ImmichServerInfo,
    ImmichSharedLink,
)


class TestImmichServerInfo:
    """Tests for the ImmichServerInfo model."""

    def test_parse_full_response(self) -> None:
        """Parse a complete server about response."""
        data = {"version": "v1.106.4", "licensed": True}
        info = ImmichServerInfo.model_validate(data)

        assert info.version == "v1.106.4"
        assert info.licensed is True

    def test_parse_minimal_response(self) -> None:
        """Parse a response with only required fields."""
        data = {"version": "v1.100.0"}
        info = ImmichServerInfo.model_validate(data)

        assert info.version == "v1.100.0"
        assert info.licensed is False

    def test_ignores_extra_fields(self) -> None:
        """Extra fields from future API versions are silently ignored."""
        data = {"version": "v2.0.0", "licensed": False, "newField": "surprise"}
        info = ImmichServerInfo.model_validate(data)

        assert info.version == "v2.0.0"


class TestImmichPerson:
    """Tests for the ImmichPerson model."""

    def test_parse_full_person(self) -> None:
        """Parse a person with all fields populated."""
        data = {
            "id": "abc-123",
            "name": "Alice",
            "birthDate": "1990-05-15",
            "thumbnailPath": "/path/to/thumb.jpg",
            "isHidden": False,
        }
        person = ImmichPerson.model_validate(data)

        assert person.id == "abc-123"
        assert person.name == "Alice"
        assert person.birth_date == "1990-05-15"
        assert person.thumbnail_path == "/path/to/thumb.jpg"
        assert person.is_hidden is False

    def test_parse_unnamed_person(self) -> None:
        """Parse a person with an empty name (unnamed face)."""
        data = {
            "id": "def-456",
            "name": "",
            "birthDate": None,
            "thumbnailPath": "",
            "isHidden": True,
        }
        person = ImmichPerson.model_validate(data)

        assert person.name == ""
        assert person.birth_date is None
        assert person.is_hidden is True

    def test_parse_minimal_person(self) -> None:
        """Parse a person with only required fields."""
        data = {"id": "xyz-789", "name": "Bob", "birthDate": None, "thumbnailPath": ""}
        person = ImmichPerson.model_validate(data)

        assert person.id == "xyz-789"
        assert person.is_hidden is False

    def test_snake_case_access(self) -> None:
        """Fields are accessible via snake_case attribute names."""
        data = {
            "id": "test-1",
            "name": "Test",
            "birthDate": "2000-01-01",
            "thumbnailPath": "/thumb",
            "isHidden": True,
        }
        person = ImmichPerson.model_validate(data)

        assert person.birth_date == "2000-01-01"
        assert person.thumbnail_path == "/thumb"
        assert person.is_hidden is True


class TestImmichPeopleResponse:
    """Tests for the ImmichPeopleResponse model."""

    def test_parse_people_list(self) -> None:
        """Parse a people list response."""
        data = {
            "people": [
                {
                    "id": "p1",
                    "name": "Alice",
                    "birthDate": None,
                    "thumbnailPath": "/t1",
                    "isHidden": False,
                },
                {
                    "id": "p2",
                    "name": "Bob",
                    "birthDate": "1985-03-20",
                    "thumbnailPath": "/t2",
                    "isHidden": True,
                },
            ],
            "total": 10,
            "hidden": 3,
            "hasNextPage": True,
        }
        resp = ImmichPeopleResponse.model_validate(data)

        assert len(resp.people) == 2
        assert resp.total == 10
        assert resp.hidden == 3
        assert resp.has_next_page is True
        assert resp.people[0].name == "Alice"
        assert resp.people[1].birth_date == "1985-03-20"


class TestImmichAsset:
    """Tests for the ImmichAsset model."""

    def test_parse_full_asset(self) -> None:
        """Parse an asset with people and exif info."""
        data = {
            "id": "asset-1",
            "type": "IMAGE",
            "originalFileName": "photo.jpg",
            "takenAt": "2024-01-15T10:30:00.000Z",
            "people": [
                {"id": "p1", "name": "Alice"},
                {"id": "p2", "name": "Bob"},
            ],
            "exifInfo": {
                "dateTimeOriginal": "2024-01-15T10:30:00.000Z",
                "timezone": "Australia/Sydney",
            },
        }
        asset = ImmichAsset.model_validate(data)

        assert asset.id == "asset-1"
        assert asset.type == "IMAGE"
        assert asset.original_file_name == "photo.jpg"
        assert asset.taken_at is not None
        assert len(asset.people) == 2
        assert asset.people[0].name == "Alice"
        assert asset.exif_info is not None
        assert asset.exif_info.timezone == "Australia/Sydney"

    def test_parse_minimal_asset(self) -> None:
        """Parse an asset with only required fields."""
        data = {"id": "asset-2"}
        asset = ImmichAsset.model_validate(data)

        assert asset.id == "asset-2"
        assert asset.type == "IMAGE"
        assert asset.people == []
        assert asset.exif_info is None


class TestImmichAlbum:
    """Tests for the ImmichAlbum model."""

    def test_parse_full_album(self) -> None:
        """Parse an album with all fields."""
        data = {
            "id": "album-1",
            "albumName": "Holiday 2024",
            "description": "Our trip to Japan",
            "albumThumbnailAssetId": "asset-1",
            "assetCount": 42,
            "assets": [{"id": "asset-1", "type": "IMAGE"}],
            "updatedAt": "2024-06-15T12:00:00.000Z",
            "shared": True,
        }
        album = ImmichAlbum.model_validate(data)

        assert album.id == "album-1"
        assert album.album_name == "Holiday 2024"
        assert album.description == "Our trip to Japan"
        assert album.album_thumbnail_asset_id == "asset-1"
        assert album.asset_count == 42
        assert len(album.assets) == 1
        assert album.shared is True

    def test_parse_empty_album(self) -> None:
        """Parse an album with no assets."""
        data = {
            "id": "album-2",
            "albumName": "Empty",
            "description": "",
            "albumThumbnailAssetId": None,
            "assetCount": 0,
        }
        album = ImmichAlbum.model_validate(data)

        assert album.album_thumbnail_asset_id is None
        assert album.asset_count == 0
        assert album.assets == []
        assert album.shared is False


class TestImmichSharedLink:
    """Tests for the ImmichSharedLink model."""

    def test_parse_album_shared_link(self) -> None:
        """Parse a shared link for an album."""
        data: dict[str, Any] = {
            "id": "link-1",
            "key": "abc123",
            "type": "ALBUM",
            "createdAt": "2024-03-10T08:00:00.000Z",
            "description": "Family photos",
            "album": {
                "id": "album-1",
                "albumName": "Family",
                "description": "",
                "albumThumbnailAssetId": None,
                "assetCount": 5,
            },
            "assets": [],
            "password": None,
            "expiresAt": "2025-03-10T08:00:00.000Z",
            "allowDownload": True,
            "allowUpload": False,
        }
        link = ImmichSharedLink.model_validate(data)

        assert link.id == "link-1"
        assert link.key == "abc123"
        assert link.type == "ALBUM"
        assert link.album is not None
        assert link.album.album_name == "Family"
        assert link.allow_download is True
        assert link.expires_at is not None
        assert link.password is None

    def test_parse_individual_shared_link(self) -> None:
        """Parse a shared link for individual assets."""
        data = {
            "id": "link-2",
            "key": "xyz789",
            "type": "INDIVIDUAL",
            "createdAt": "2024-03-10T08:00:00.000Z",
            "assets": [{"id": "asset-1"}, {"id": "asset-2"}],
            "allowDownload": False,
            "allowUpload": True,
        }
        link = ImmichSharedLink.model_validate(data)

        assert link.type == "INDIVIDUAL"
        assert link.album is None
        assert len(link.assets) == 2
        assert link.allow_download is False
        assert link.allow_upload is True

    def test_parse_minimal_shared_link(self) -> None:
        """Parse a shared link with only required fields."""
        data = {"id": "link-3", "key": "min123"}
        link = ImmichSharedLink.model_validate(data)

        assert link.id == "link-3"
        assert link.key == "min123"
        assert link.type == "ALBUM"
        assert link.assets == []


class TestImmichModelsExtraFieldHandling:
    """Verify all models tolerate unknown fields from newer API versions."""

    @pytest.mark.parametrize(
        ("model_class", "data"),
        [
            (ImmichServerInfo, {"version": "v1.0", "brandNew": True}),
            (
                ImmichPerson,
                {
                    "id": "p",
                    "name": "X",
                    "birthDate": None,
                    "thumbnailPath": "",
                    "unknownProp": 42,
                },
            ),
            (ImmichAlbum, {"id": "a", "newAlbumField": []}),
            (ImmichAsset, {"id": "a", "futureField": {"nested": True}}),
            (ImmichSharedLink, {"id": "l", "key": "k", "extraData": "val"}),
        ],
    )
    def test_extra_fields_ignored(
        self,
        model_class: Any,
        data: dict[str, object],
    ) -> None:
        """Extra fields are silently ignored by all models."""
        obj = model_class.model_validate(data)
        assert obj.id if hasattr(obj, "id") else obj.version
