"""Unit tests for the activity-stats filter parsing."""

import pytest

from app.core.journal.models.activity_stats import parse_activity_type


class TestParseActivityType:
    def test_none_means_no_filter(self) -> None:
        assert parse_activity_type(None) is None

    def test_normalises_case_and_whitespace(self) -> None:
        assert parse_activity_type("  Cross_Country_Skiing ") == "cross_country_skiing"

    def test_rejects_a_journal_type_that_is_not_an_activity(self) -> None:
        with pytest.raises(
            ValueError,
            match=(
                r"^Invalid activity_type 'note'\. Must be one of: abseiling_trip, "
                r"bushwalking, canyoning, caving, climbing, cross_country_skiing, "
                r"fitness, jogging, kayaking, outdoor_activity$"
            ),
        ):
            parse_activity_type("note")
