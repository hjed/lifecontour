"""Abseiling service for the journal domain.

This service encapsulates business logic for ABSEILING_TRIP journal types,
including auto-calculation of aggregate totals based on pitch data.
"""

import dataclasses

from core_shared.models.journals.abseil_pitch import AbseilPitch
from core_shared.models.journals.abseiling_data import AbseilingData
from core_shared.models.journals.exceptions import JournalValidationError

from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
)


class AbseilingService:
    """Service for handling Abseiling business logic and calculations."""

    def __init__(self) -> None:
        pass

    def calculate_abseiling_totals(
        self, abseiling_data: AbseilingData, pitches: list[AbseilPitch]
    ) -> AbseilingData:
        """
        Auto-calculate abseiling totals from pitches if manual overrides are not provided.

        Manual overrides (when the user provides a value directly on the AbseilingData)
        always take precedence over auto-calculated values from pitches.

        Args:
            abseiling_data: The existing or requested AbseilingData.
            pitches: The list of pitches associated with this journal.

        Returns:
            A new AbseilingData instance with updated calculations.
        """
        # Calculate totals from pitches
        calculated_abseils = len(pitches)
        calculated_length = sum((p.height for p in pitches if p.height is not None), 0)
        calculated_setups = sum(1 for p in pitches if p.did_setup)
        calculated_rescues = sum(1 for p in pitches if p.did_rescue)

        # Apply calculations only if the field is not already populated with a manual override
        # Wait, if a user sends an update, how do we distinguish between "user kept the old value"
        # and "user wants an explicit override"?
        # The prompt says: "Manual override: user-provided totals take precedence over auto-calculated values"
        # Since we only get the resulting `abseiling_data` object in the payload (which contains whatever
        # the client explicitly sent), if it's set in `abseiling_data`, it takes precedence.

        # However, what if the user edits a pitch but leaves the 'manual' total the same as before?
        # Typically, the client either sends a null/empty field to rely on auto-calculation, or explicitly
        # sends a value to override. For this service layer, we will assume that if `abseiling_data` has a
        # non-None value, it's a manual override.

        from typing import Any

        updates: dict[str, Any] = {}
        if abseiling_data.number_of_abseils is None:
            updates["number_of_abseils"] = calculated_abseils
        if abseiling_data.total_length is None:
            updates["total_length"] = calculated_length
        if abseiling_data.number_of_setups is None:
            updates["number_of_setups"] = calculated_setups
        if abseiling_data.number_of_rescues is None:
            updates["number_of_rescues"] = calculated_rescues

        if updates:
            return dataclasses.replace(abseiling_data, **updates)

        return abseiling_data

    async def update_abseiling_data(
        self,
        abseiling_data_repo: AbseilingDataRepository,
        abseil_pitch_repo: AbseilPitchRepository,
        abseiling_data: AbseilingData,
        pitches: list[AbseilPitch] | None = None,
    ) -> AbseilingData:
        """
        Save abseiling data and associated pitches.

        This handles calculating totals from pitches, saving the AbseilingData,
        and hard-replacing (delete and recreate) the pitches to avoid complex diffs.

        Args:
            abseiling_data_repo: Repository for AbseilingData
            abseil_pitch_repo: Repository for AbseilPitch
            abseiling_data: The AbseilingData to save
            pitches: The pitches to replace existing ones, or None to leave pitches unchanged.
                     If an empty list is provided, all existing pitches are deleted.
        """
        # If pitches are provided (even empty list), perform calculation
        if pitches is not None:
            seen_pitch_numbers = set()
            for pitch in pitches:
                if pitch.pitch_number in seen_pitch_numbers:
                    raise JournalValidationError(
                        "pitches", f"Duplicate pitch number found: {pitch.pitch_number}"
                    )
                seen_pitch_numbers.add(pitch.pitch_number)

            abseiling_data = self.calculate_abseiling_totals(abseiling_data, pitches)

        # Save AbseilingData
        await abseiling_data_repo.save(abseiling_data)

        # Handle pitch persistence if provided
        if pitches is not None:
            # Delete existing
            await abseil_pitch_repo.delete_by_journal_id(abseiling_data.journal_id)
            # Recreate new
            for pitch in pitches:
                pitch.journal_id = abseiling_data.journal_id
                await abseil_pitch_repo.save(pitch)

        return abseiling_data
