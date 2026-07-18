from core_shared.models.journals.abseil_pitch import AbseilPitch
from core_shared.models.journals.abseiling_data import AbseilingData

from app.core.journal.services.abseiling_service import AbseilingService


def test_auto_calculation_no_pitches():
    """Test that manual totals are preserved when no pitches are provided."""
    service = AbseilingService()

    # Original data with manual totals
    data = AbseilingData(
        journal_id=1,
        number_of_abseils=5,
        total_length=100,
        number_of_setups=2,
        number_of_rescues=1,
    )

    # Update with no pitches should just keep the manual totals
    updated_data = service.calculate_abseiling_totals(data, pitches=[])

    assert updated_data.number_of_abseils == 5
    assert updated_data.total_length == 100
    assert updated_data.number_of_setups == 2
    assert updated_data.number_of_rescues == 1


def test_auto_calculation_with_pitches_no_manual_totals():
    """Test auto-calculation when pitches are provided and manual totals are not."""
    service = AbseilingService()

    data = AbseilingData(journal_id=1)
    pitches = [
        AbseilPitch(
            journal_id=1, pitch_number=1, height=10, did_setup=True, did_rescue=False
        ),
        AbseilPitch(
            journal_id=1, pitch_number=2, height=15, did_setup=False, did_rescue=True
        ),
        AbseilPitch(
            journal_id=1, pitch_number=3, height=20, did_setup=True, did_rescue=True
        ),
        AbseilPitch(
            journal_id=1, pitch_number=4, height=None, did_setup=False, did_rescue=False
        ),
    ]

    updated_data = service.calculate_abseiling_totals(data, pitches=pitches)

    assert updated_data.number_of_abseils == 4  # 4 pitches
    assert updated_data.total_length == 45  # 10 + 15 + 20
    assert updated_data.number_of_setups == 2  # 2 true
    assert updated_data.number_of_rescues == 2  # 2 true


def test_auto_calculation_counts_only_abseil_pitches():
    """number_of_abseils counts only abseil-type pitches; other totals count all.

    A jump or down-climb pitch still descends its height, so total_length,
    setups, and rescues include every pitch regardless of type.
    """
    service = AbseilingService()

    data = AbseilingData(journal_id=1)
    pitches = [
        AbseilPitch(journal_id=1, pitch_number=1, height=10, did_setup=True),
        AbseilPitch(journal_id=1, pitch_number=2, height=15, pitch_type="abseil"),
        AbseilPitch(
            journal_id=1, pitch_number=3, height=5, pitch_type="jump", did_rescue=True
        ),
        AbseilPitch(journal_id=1, pitch_number=4, height=3, pitch_type="down_climb"),
    ]

    updated_data = service.calculate_abseiling_totals(data, pitches=pitches)

    # None and "abseil" both count as abseils; jump and down_climb do not.
    assert updated_data.number_of_abseils == 2
    assert updated_data.total_length == 33  # all pitches descend their height
    assert updated_data.number_of_setups == 1
    assert updated_data.number_of_rescues == 1


def test_auto_calculation_manual_override_precedence():
    """Test that manual totals take precedence over auto-calculation."""
    service = AbseilingService()

    # User provides manual overrides that differ from the pitch calculations
    data = AbseilingData(
        journal_id=1,
        number_of_abseils=10,  # override
        total_length=200,  # override
        number_of_setups=5,  # override
        number_of_rescues=3,  # override
    )

    pitches = [
        AbseilPitch(
            journal_id=1, pitch_number=1, height=10, did_setup=True, did_rescue=False
        ),
        AbseilPitch(
            journal_id=1, pitch_number=2, height=15, did_setup=False, did_rescue=True
        ),
    ]

    updated_data = service.calculate_abseiling_totals(data, pitches=pitches)

    # Manual overrides should take precedence
    assert updated_data.number_of_abseils == 10
    assert updated_data.total_length == 200
    assert updated_data.number_of_setups == 5
    assert updated_data.number_of_rescues == 3
