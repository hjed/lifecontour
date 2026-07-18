"""Unit tests for TemplatePitch entity."""

import pytest
from core_shared.models.journals import TemplatePitchValidationError
from core_shared.models.journals.template_pitch import TemplatePitch


@pytest.mark.unit
class TestTemplatePitch:
    """Test TemplatePitch entity validation."""

    def test_create_template_pitch_minimal(self):
        """Test creating a template pitch with only required fields."""
        pitch = TemplatePitch(
            template_id="12345678-1234-5678-1234-567812345678", pitch_number=1
        )

        assert pitch.template_id == "12345678-1234-5678-1234-567812345678"
        assert pitch.pitch_number == 1
        assert pitch.id is None
        assert pitch.height is None
        assert pitch.anchor_location is None
        assert pitch.anchor_type is None
        assert pitch.did_rescue is None
        assert pitch.did_setup is None
        assert pitch.notes is None
        assert pitch.pitch_type is None
        assert pitch.created_at is None
        assert pitch.updated_at is None

    # --- pitch_type validation ---

    @pytest.mark.parametrize("pitch_type", ["abseil", "jump", "down_climb"])
    def test_valid_pitch_types(self, pitch_type: str):
        """Test all valid pitch type values."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            pitch_type=pitch_type,
        )
        assert pitch.pitch_type == pitch_type

    def test_invalid_pitch_type(self):
        """Test that an invalid pitch type raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(
                template_id="87654321-4321-8765-4321-876543210987",
                pitch_number=1,
                pitch_type="swim",
            )

        assert "pitch_type" in str(exc_info.value)

    def test_none_pitch_type_valid(self):
        """Test that None pitch type is valid (defaults to abseil semantics)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            pitch_type=None,
        )
        assert pitch.pitch_type is None

    def test_create_template_pitch_with_all_fields(self):
        """Test creating a template pitch with all fields populated."""
        pitch = TemplatePitch(
            template_id="12345678-1234-5678-1234-567812345678",
            pitch_number=3,
            id=42,
            height=25,
            anchor_location="TR",
            anchor_type="double bolt",
            did_rescue=True,
            did_setup=False,
            notes="Awkward start over the chockstone",
        )

        assert pitch.template_id == "12345678-1234-5678-1234-567812345678"
        assert pitch.pitch_number == 3
        assert pitch.id == 42
        assert pitch.height == 25
        assert pitch.anchor_location == "TR"
        assert pitch.anchor_type == "double bolt"
        assert pitch.did_rescue is True
        assert pitch.did_setup is False
        assert pitch.notes == "Awkward start over the chockstone"

    # --- template_id validation ---

    def test_invalid_template_id_empty(self):
        """Test that empty template_id raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(template_id="", pitch_number=1)

        assert "template_id" in str(exc_info.value)

    # --- pitch_number validation ---

    def test_invalid_pitch_number_zero(self):
        """Test that pitch_number of 0 raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(
                template_id="87654321-4321-8765-4321-876543210987", pitch_number=0
            )

        assert "pitch_number" in str(exc_info.value)

    def test_invalid_pitch_number_negative(self):
        """Test that negative pitch_number raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(
                template_id="87654321-4321-8765-4321-876543210987", pitch_number=-5
            )

        assert "pitch_number" in str(exc_info.value)

    def test_valid_pitch_number_one(self):
        """Test that pitch_number of 1 is valid (boundary)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987", pitch_number=1
        )
        assert pitch.pitch_number == 1

    def test_valid_pitch_number_large(self):
        """Test that a large pitch_number is valid."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987", pitch_number=100
        )
        assert pitch.pitch_number == 100

    # --- height validation ---

    def test_valid_height_zero(self):
        """Test that height of 0 is valid."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987", pitch_number=1, height=0
        )
        assert pitch.height == 0

    def test_invalid_height_negative(self):
        """Test that negative height raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(
                template_id="87654321-4321-8765-4321-876543210987",
                pitch_number=1,
                height=-10,
            )

        assert "height" in str(exc_info.value)

    def test_none_height_valid(self):
        """Test that None height is valid (field is optional)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            height=None,
        )
        assert pitch.height is None

    # --- anchor_location validation ---

    @pytest.mark.parametrize("location", ["TR", "TL", "Centre"])
    def test_valid_anchor_locations(self, location: str):
        """Test all valid anchor location values."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            anchor_location=location,
        )
        assert pitch.anchor_location == location

    def test_invalid_anchor_location(self):
        """Test that an invalid anchor location raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(
                template_id="87654321-4321-8765-4321-876543210987",
                pitch_number=1,
                anchor_location="Bottom",
            )

        assert "anchor_location" in str(exc_info.value)

    def test_none_anchor_location_valid(self):
        """Test that None anchor location is valid (field is optional)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            anchor_location=None,
        )
        assert pitch.anchor_location is None

    # --- anchor_type validation ---

    @pytest.mark.parametrize(
        "anchor_type",
        [
            "chains",
            "double bolt",
            "single bolt",
            "sling on tree",
            "sling on log",
            "sling on boulder",
            "sling on bollard",
            "artificial removable",
        ],
    )
    def test_valid_anchor_types(self, anchor_type: str):
        """Test all valid anchor type values."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            anchor_type=anchor_type,
        )
        assert pitch.anchor_type == anchor_type

    def test_invalid_anchor_type(self):
        """Test that an invalid anchor type raises validation error."""
        with pytest.raises(TemplatePitchValidationError) as exc_info:
            TemplatePitch(
                template_id="87654321-4321-8765-4321-876543210987",
                pitch_number=1,
                anchor_type="rope bridge",
            )

        assert "anchor_type" in str(exc_info.value)

    def test_none_anchor_type_valid(self):
        """Test that None anchor type is valid (field is optional)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            anchor_type=None,
        )
        assert pitch.anchor_type is None

    # --- boolean fields ---

    def test_did_rescue_true(self):
        """Test did_rescue set to True."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            did_rescue=True,
        )
        assert pitch.did_rescue is True

    def test_did_rescue_false(self):
        """Test did_rescue set to False."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            did_rescue=False,
        )
        assert pitch.did_rescue is False

    def test_did_rescue_none(self):
        """Test did_rescue set to None (field is optional)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            did_rescue=None,
        )
        assert pitch.did_rescue is None

    def test_did_setup_true(self):
        """Test did_setup set to True."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            did_setup=True,
        )
        assert pitch.did_setup is True

    def test_did_setup_false(self):
        """Test did_setup set to False."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            did_setup=False,
        )
        assert pitch.did_setup is False

    def test_did_setup_none(self):
        """Test did_setup set to None (field is optional)."""
        pitch = TemplatePitch(
            template_id="87654321-4321-8765-4321-876543210987",
            pitch_number=1,
            did_setup=None,
        )
        assert pitch.did_setup is None
