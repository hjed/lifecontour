"""Calculators for logbook export data."""

from dataclasses import dataclass, field

from .logbook_export import (
    ActivityTypeIndexEntry,
    LogbookEntryData,
    LogbookIndexJournal,
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
                "OUTDOOR_ACTIVITY",
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
                    if pitch.height is not None:
                        summary.total_abseiling_metres += pitch.height
                    if pitch.did_setup:
                        summary.total_setups += 1
                    if pitch.did_rescue:
                        summary.total_rescues += 1

            # Sub-entries
            for child in entry.children:
                process_entry(child)

        for entry in entries:
            process_entry(entry)

        return sorted(summaries_by_year.values(), key=lambda s: s.year, reverse=True)


@dataclass
class _ParticipantAppearances:
    """A contact's accumulated appearances while building the index.

    The appearance count is not tracked separately — it is the length of
    ``journals``, so the count and the linked list cannot disagree.
    """

    name: str
    journals: list[LogbookIndexJournal] = field(default_factory=list)


# The relationship types the participant index counts.
_INDEXED_ROLES = ("PARTICIPANT", "INVITEE")


def _indexed_contacts(entry: LogbookEntryData) -> dict[int, str]:
    """Map contact id to name for everyone indexed on an entry or its children.

    Collapsing the subtree into one mapping is what makes a contact listed on
    both a trip and its child activities count once for that trip.
    """
    contacts = {
        contact.contact_id: contact.name
        for contact in entry.contacts
        if contact.role in _INDEXED_ROLES
    }
    for child in entry.children:
        contacts.update(_indexed_contacts(child))
    return contacts


class ParticipantIndexCalculator:
    """Calculates the participant index from logbook entries."""

    def calculate(
        self, entries: list[LogbookEntryData], min_appearances: int = 3
    ) -> list[ParticipantIndexEntry]:
        """Calculate the participant index for contacts with >= min_appearances.

        Each qualifying contact also carries the root entries they appear in,
        so the PDF index can link to them. Appearances are counted per root
        entry, so ``appearances == len(journals)`` holds by construction and a
        contact listed on both a trip and its child activities is counted once.
        """
        appearances_by_root: dict[int, _ParticipantAppearances] = {}
        for entry in entries:
            for contact_id, name in _indexed_contacts(entry).items():
                accumulator = appearances_by_root.setdefault(
                    contact_id, _ParticipantAppearances(name=name)
                )
                # Counting the appearance and recording its link are the same
                # step, so the count can never drift from the linked list.
                accumulator.journals.append(
                    LogbookIndexJournal(journal_id=entry.id, title=entry.title)
                )

        return sorted(
            (
                ParticipantIndexEntry(
                    contact_id=contact_id,
                    name=accumulator.name,
                    appearances=len(accumulator.journals),
                    journals=accumulator.journals,
                )
                for contact_id, accumulator in appearances_by_root.items()
                if len(accumulator.journals) >= min_appearances
            ),
            key=lambda participant: participant.name,
        )


class ActivityTypeIndexCalculator:
    """Calculates the activity-type index from logbook entries."""

    def calculate(
        self, entries: list[LogbookEntryData]
    ) -> list[ActivityTypeIndexEntry]:
        """Group every entry under each of the journal types it carries.

        Type rows are listed verbatim: a canyoning journal also carries the
        bushwalking, abseiling and outdoor-activity rows its type depends on,
        and appears under all of them. Sections are type-sorted; the journals
        within a section keep document order (roots and their nested activities
        in the order the PDF renders them).
        """
        journals_by_type: dict[str, list[LogbookIndexJournal]] = {}
        seen_by_type: dict[str, set[int]] = {}

        def index_entry(entry: LogbookEntryData) -> None:
            for activity_type in entry.journal_types:
                seen = seen_by_type.setdefault(activity_type, set())
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                journals_by_type.setdefault(activity_type, []).append(
                    LogbookIndexJournal(journal_id=entry.id, title=entry.title)
                )
            for child in entry.children:
                index_entry(child)

        for entry in entries:
            index_entry(entry)

        return [
            ActivityTypeIndexEntry(
                activity_type=activity_type, journals=journals_by_type[activity_type]
            )
            for activity_type in sorted(journals_by_type)
        ]
