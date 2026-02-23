"""Unit tests for CanyoningData entity (CANYONING type).

French Canyon Grading System:
  Format: v[vertical]a[aquatic][engagement][stars]
  Example: v3a2IV** = vertical grade 3, aquatic grade 2, engagement IV, 2 stars
  - Vertical: 1-7 (difficulty of abseils)
  - Aquatic: 1-7 (difficulty of water sections)
  - Engagement: I-VI (commitment level, optional)
  - Stars: * to *** (quality/beauty, optional)
"""

from uuid import UUID, uuid4

import pytest

from app.core.journal.models.canyoning_data import CanyoningData
from app.core.journal.models.exceptions import CanyoningDataValidationError


@pytest.mark.unit
class TestCanyoningData:
    """Test CanyoningData entity."""

    def test_create_canyoning_data_minimal(self):
        """Test creating canyoning data with only required fields."""
        data = CanyoningData(journal_id=1)

        assert data.journal_id == 1
        assert data.route_id is None
        assert data.french_grade is None
        assert data.water_guage_name is None
        assert data.water_guage_level is None
        assert data.is_vertical is None
        assert data.is_night_canyon is None
        assert data.is_white_water is None
        assert data.created_at is None
        assert data.updated_at is None

    def test_create_canyoning_data_with_route(self):
        """Test creating canyoning data with a route ID."""
        route_id = uuid4()
        data = CanyoningData(journal_id=1, route_id=route_id)

        assert data.route_id == route_id

    def test_create_canyoning_data_with_all_fields(self):
        """Test creating canyoning data with all optional fields populated."""
        route_id = uuid4()
        data = CanyoningData(
            journal_id=3,
            route_id=route_id,
            french_grade="v3a2IV**",
            water_guage_name="Claustral Brook Gauge",
            water_guage_level=42,
            is_vertical=True,
            is_night_canyon=False,
            is_white_water=True,
        )

        assert data.journal_id == 3
        assert data.route_id == route_id
        assert data.french_grade == "v3a2IV**"
        assert data.water_guage_name == "Claustral Brook Gauge"
        assert data.water_guage_level == 42
        assert data.is_vertical is True
        assert data.is_night_canyon is False
        assert data.is_white_water is True

    def test_french_grade_vertical_only(self):
        """Test valid French grade with only vertical and aquatic components."""
        data = CanyoningData(journal_id=1, french_grade="v1a1")
        assert data.french_grade == "v1a1"

    def test_french_grade_max_components(self):
        """Test valid French grade with all components at maximum."""
        data = CanyoningData(journal_id=1, french_grade="v7a7VI***")
        assert data.french_grade == "v7a7VI***"

    def test_french_grade_with_engagement_no_stars(self):
        """Test valid French grade with engagement but no stars."""
        data = CanyoningData(journal_id=1, french_grade="v3a2IV")
        assert data.french_grade == "v3a2IV"

    def test_french_grade_with_stars_no_engagement(self):
        """Test valid French grade with stars but no engagement."""
        data = CanyoningData(journal_id=1, french_grade="v3a2**")
        assert data.french_grade == "v3a2**"

    def test_french_grade_engagement_iv(self):
        """Test valid French grade with engagement IV."""
        data = CanyoningData(journal_id=1, french_grade="v4a3IV*")
        assert data.french_grade == "v4a3IV*"

    def test_french_grade_engagement_roman_numerals(self):
        """Test valid French grades with all Roman numeral engagements."""
        for engagement in ["I", "II", "III", "IV", "V", "VI"]:
            data = CanyoningData(journal_id=1, french_grade=f"v3a2{engagement}")
            assert data.french_grade == f"v3a2{engagement}"

    def test_invalid_journal_id_zero(self):
        """Test that journal_id of 0 raises validation error."""
        with pytest.raises(CanyoningDataValidationError) as exc_info:
            CanyoningData(journal_id=0)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_journal_id_negative(self):
        """Test that negative journal_id raises validation error."""
        with pytest.raises(CanyoningDataValidationError) as exc_info:
            CanyoningData(journal_id=-3)

        assert "journal_id" in str(exc_info.value)

    def test_invalid_french_grade_format(self):
        """Test that an invalid French grade format raises validation error."""
        with pytest.raises(CanyoningDataValidationError) as exc_info:
            CanyoningData(journal_id=1, french_grade="grade3")

        assert "french_grade" in str(exc_info.value)

    def test_invalid_french_grade_out_of_range_vertical(self):
        """Test that vertical grade out of 1-7 range raises validation error."""
        with pytest.raises(CanyoningDataValidationError) as exc_info:
            CanyoningData(journal_id=1, french_grade="v8a2IV")

        assert "french_grade" in str(exc_info.value)

    def test_invalid_french_grade_out_of_range_aquatic(self):
        """Test that aquatic grade out of 1-7 range raises validation error."""
        with pytest.raises(CanyoningDataValidationError) as exc_info:
            CanyoningData(journal_id=1, french_grade="v3a8IV")

        assert "french_grade" in str(exc_info.value)

    def test_invalid_french_grade_empty_string(self):
        """Test that empty french grade string raises validation error."""
        with pytest.raises(CanyoningDataValidationError) as exc_info:
            CanyoningData(journal_id=1, french_grade="")

        assert "french_grade" in str(exc_info.value)

    def test_none_french_grade_is_valid(self):
        """Test that None french_grade is valid (field is optional)."""
        data = CanyoningData(journal_id=1, french_grade=None)

        assert data.french_grade is None

    def test_route_id_is_uuid(self):
        """Test that route_id must be a UUID."""
        route_id = UUID("12345678-1234-5678-1234-567812345678")
        data = CanyoningData(journal_id=1, route_id=route_id)

        assert isinstance(data.route_id, UUID)
