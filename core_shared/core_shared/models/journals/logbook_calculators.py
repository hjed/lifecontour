"""Calculators for logbook export data."""

from typing import Any

from .logbook_export import (
    LogbookEntryData,
    LogbookYearlySummary,
    ParticipantIndexEntry,
)


class LogbookSummaryCalculator:
    """Calculates yearly summaries from logbook entries."""

    def calculate(self, entries: list[LogbookEntryData]) -> list[LogbookYearlySummary]:
        """Calculate yearly statistics from logbook entries."""
        summaries_by_year: dict[int, LogbookYearlySummary] = {}

        def process_entry(entry: LogbookEntryData) -> None:
            year = entry.event_date_range.start.year
            if year not in summaries_by_year:
                summaries_by_year[year] = LogbookYearlySummary(year=year)

            summary = summaries_by_year[year]

            # Count activities by type
            # We specifically count subtypes or specific top-level types (like GEAR_MAINTENANCE)
            # Find the most specific outdoor activity subtype if any
            primary_type = None

            # The type is determined by the types list
            outdoor_types = [
                "BUSHWALKING",
                "CANYONING",
                "CAVING",
                "CLIMBING",
                "KAYAKING",
                "CANOEING",
                "SNORKELLING",
                "DIVING",
                "CROSS_COUNTRY_SKIING",
                "DOWNHILL_SKIING",
                "ABSEILING_TRIP",
            ]

            for o_type in outdoor_types:
                if o_type in entry.journal_types:
                    primary_type = o_type
                    break

            if not primary_type:
                if "GEAR_MAINTENANCE" in entry.journal_types:
                    primary_type = "GEAR_MAINTENANCE"
                elif "OUTDOOR_TRAINING" in entry.journal_types:
                    primary_type = "OUTDOOR_TRAINING"
                elif "OUTDOOR_PLANNING" in entry.journal_types:
                    primary_type = "OUTDOOR_PLANNING"

            if primary_type:
                summary.total_activities_by_type[primary_type] = (
                    summary.total_activities_by_type.get(primary_type, 0) + 1
                )

                # Check leadership
                if (
                    entry.outdoor_activity_data
                    and entry.outdoor_activity_data.in_leadership_role
                ):
                    summary.leadership_activities_by_type[primary_type] = (
                        summary.leadership_activities_by_type.get(primary_type, 0) + 1
                    )

            # Abseiling stats
            if entry.abseil_pitches:
                for pitch in entry.abseil_pitches:
                    summary.total_abseils += 1
                    if pitch.height:
                        summary.total_abseiling_metres += pitch.height
                    if pitch.did_setup:
                        summary.total_setups += 1

            # Sub-entries
            for child in entry.children:
                process_entry(child)

        for entry in entries:
            process_entry(entry)

        return sorted(summaries_by_year.values(), key=lambda s: s.year, reverse=True)


class ParticipantIndexCalculator:
    """Calculates the participant index from logbook entries."""

    def calculate(
        self, entries: list[LogbookEntryData], min_appearances: int = 3
    ) -> list[ParticipantIndexEntry]:
        """Calculate the participant index for contacts with >= min_appearances."""
        # The spec says "Frequent contacts who appear in more than 3 entries".
        # Let's count them per root entry to avoid double counting if they appear in sub-entries.

        appearances_by_root: dict[int, dict[str, Any]] = {}
        for entry in entries:
            entry_contacts: set[int] = set()
            names: dict[int, str] = {}

            def collect_contacts(
                e: LogbookEntryData, contacts_set: set[int], names_dict: dict[int, str]
            ) -> None:
                for c in e.contacts:
                    contacts_set.add(c.contact_id)
                    names_dict[c.contact_id] = c.name
                for child in e.children:
                    collect_contacts(child, contacts_set, names_dict)

            collect_contacts(entry, entry_contacts, names)

            for cid in entry_contacts:
                if cid not in appearances_by_root:
                    appearances_by_root[cid] = {"name": names[cid], "count": 0}
                appearances_by_root[cid]["count"] += 1

        result = []
        for cid, data in appearances_by_root.items():
            if data["count"] >= min_appearances:
                result.append(
                    ParticipantIndexEntry(
                        contact_id=cid,
                        name=data["name"],
                        appearances=data["count"],
                    )
                )

        return sorted(result, key=lambda p: p.name)
