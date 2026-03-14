"""Unit tests for FitnessData entity (FITNESS type)."""

import pytest
from core_shared.models.journals import FitnessData, FitnessDataValidationError


@pytest.mark.unit
class TestFitnessData:
    """Test FitnessData entity."""

    def test_create_fitness_data_minimal(self):
        """Test creating fitness data with minimal required fields."""
        fitness_data = FitnessData(journal_id=1)

        assert fitness_data.journal_id == 1
        assert fitness_data.heart_rate_avg is None
        assert fitness_data.heart_rate_max is None
        assert fitness_data.distance is None
        assert fitness_data.elevation_gain is None
        assert fitness_data.elevation_loss is None
        assert fitness_data.duration is None
        assert fitness_data.calories is None
        assert fitness_data.gpx_track_data is None
        assert fitness_data.strava_activity_id is None

    def test_create_fitness_data_with_heart_rate(self):
        """Test creating fitness data with heart rate data."""
        fitness_data = FitnessData(
            journal_id=1,
            heart_rate_avg=145,
            heart_rate_max=178,
        )

        assert fitness_data.heart_rate_avg == 145
        assert fitness_data.heart_rate_max == 178

    def test_create_fitness_data_with_distance_and_elevation(self):
        """Test creating fitness data with distance and elevation."""
        fitness_data = FitnessData(
            journal_id=1,
            distance=5000,  # 5km in meters
            elevation_gain=250,
            elevation_loss=200,
        )

        assert fitness_data.distance == 5000
        assert fitness_data.elevation_gain == 250
        assert fitness_data.elevation_loss == 200

    def test_create_fitness_data_with_duration_and_calories(self):
        """Test creating fitness data with duration and calories."""
        fitness_data = FitnessData(
            journal_id=1,
            duration=3600,  # 1 hour in seconds
            calories=450,
        )

        assert fitness_data.duration == 3600
        assert fitness_data.calories == 450

    def test_create_fitness_data_with_gpx_track(self):
        """Test creating fitness data with GPX track data."""
        gpx_data = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Test Track</name>
  </trk>
</gpx>"""
        fitness_data = FitnessData(
            journal_id=1,
            gpx_track_data=gpx_data,
        )

        assert fitness_data.gpx_track_data == gpx_data

    def test_create_fitness_data_with_strava_id(self):
        """Test creating fitness data with Strava activity ID."""
        fitness_data = FitnessData(
            journal_id=1,
            strava_activity_id="12345678",
        )

        assert fitness_data.strava_activity_id == "12345678"

    def test_create_fitness_data_complete(self):
        """Test creating fitness data with all fields."""
        gpx_data = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Complete Track</name>
  </trk>
</gpx>"""
        fitness_data = FitnessData(
            journal_id=1,
            heart_rate_avg=145,
            heart_rate_max=178,
            distance=10000,
            elevation_gain=500,
            elevation_loss=450,
            duration=7200,
            calories=800,
            gpx_track_data=gpx_data,
            strava_activity_id="87654321",
        )

        assert fitness_data.journal_id == 1
        assert fitness_data.heart_rate_avg == 145
        assert fitness_data.heart_rate_max == 178
        assert fitness_data.distance == 10000
        assert fitness_data.elevation_gain == 500
        assert fitness_data.elevation_loss == 450
        assert fitness_data.duration == 7200
        assert fitness_data.calories == 800
        assert fitness_data.gpx_track_data == gpx_data
        assert fitness_data.strava_activity_id == "87654321"


@pytest.mark.unit
class TestFitnessDataValidation:
    """Test FitnessData validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            FitnessData(journal_id=0)

        with pytest.raises(
            FitnessDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            FitnessData(journal_id=-1)

    def test_negative_heart_rate_avg_raises_error(self):
        """Test that negative heart rate average raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Heart rate average must be non-negative",
        ):
            FitnessData(journal_id=1, heart_rate_avg=-1)

    def test_negative_heart_rate_max_raises_error(self):
        """Test that negative heart rate max raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Heart rate max must be non-negative",
        ):
            FitnessData(journal_id=1, heart_rate_max=-1)

    def test_negative_distance_raises_error(self):
        """Test that negative distance raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Distance must be non-negative",
        ):
            FitnessData(journal_id=1, distance=-1)

    def test_negative_elevation_gain_raises_error(self):
        """Test that negative elevation gain raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Elevation gain must be non-negative",
        ):
            FitnessData(journal_id=1, elevation_gain=-1)

    def test_negative_elevation_loss_raises_error(self):
        """Test that negative elevation loss raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Elevation loss must be non-negative",
        ):
            FitnessData(journal_id=1, elevation_loss=-1)

    def test_negative_duration_raises_error(self):
        """Test that negative duration raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Duration must be non-negative",
        ):
            FitnessData(journal_id=1, duration=-1)

    def test_negative_calories_raises_error(self):
        """Test that negative calories raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Calories must be non-negative",
        ):
            FitnessData(journal_id=1, calories=-1)

    def test_invalid_gpx_data_raises_error(self):
        """Test that invalid GPX data raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="GPX data must be valid XML",
        ):
            FitnessData(journal_id=1, gpx_track_data="not valid xml")

    def test_gpx_data_without_gpx_root_raises_error(self):
        """Test that GPX data without <gpx> root element raises error."""
        invalid_gpx = """<?xml version="1.0" encoding="UTF-8"?>
<track>
  <name>Test</name>
</track>"""
        with pytest.raises(
            FitnessDataValidationError,
            match="GPX data must have <gpx> root element",
        ):
            FitnessData(journal_id=1, gpx_track_data=invalid_gpx)

    def test_empty_strava_activity_id_raises_error(self):
        """Test that empty Strava activity ID raises error."""
        with pytest.raises(
            FitnessDataValidationError,
            match="Strava activity ID cannot be empty",
        ):
            FitnessData(journal_id=1, strava_activity_id="")

    def test_strava_activity_id_too_long_raises_error(self):
        """Test that Strava activity ID exceeding max length raises error."""
        long_id = "a" * 256  # Assuming max length of 255
        with pytest.raises(
            FitnessDataValidationError,
            match="Strava activity ID cannot exceed 255 characters",
        ):
            FitnessData(journal_id=1, strava_activity_id=long_id)
