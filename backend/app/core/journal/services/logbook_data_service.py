"""Service for gathering and calculating logbook export data."""

from core_shared.models.journals import (
    LogbookExportData,
    LogbookSummaryCalculator,
    ParticipantIndexCalculator,
)

from app.core.journal.models.repositories import LogbookExportRepository


class LogbookDataService:
    """Service to aggregate and calculate logbook export data."""

    def __init__(
        self,
        repository: LogbookExportRepository,
        summary_calculator: LogbookSummaryCalculator,
        participant_calculator: ParticipantIndexCalculator,
    ):
        """Initialize the service."""
        self.repository = repository
        self.summary_calculator = summary_calculator
        self.participant_calculator = participant_calculator

    async def get_logbook_data(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        activity_types: list[str] | None = None,
    ) -> LogbookExportData:
        """Get the full assembled logbook data."""
        # 1. Fetch all raw flat entries
        raw_entries = await self.repository.get_logbook_entries(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            activity_types=activity_types,
        )

        # 2. Assemble hierarchy
        entry_map = {entry.id: entry for entry in raw_entries}
        root_entries = []

        for entry in raw_entries:
            if entry.parent_id and entry.parent_id in entry_map:
                parent = entry_map[entry.parent_id]
                # Avoid duplicates just in case
                if entry.id not in {child.id for child in parent.children}:
                    parent.children.append(entry)
            else:
                root_entries.append(entry)

        # 3. Sort root entries by chronological order (event_date_range.start)
        # Assuming we want them chronologically ascending (oldest to newest)
        root_entries.sort(key=lambda e: e.event_date_range.start)

        # Sort children similarly
        for entry in raw_entries:
            entry.children.sort(key=lambda e: e.event_date_range.start)

        # 4. Calculate summaries
        yearly_summaries = self.summary_calculator.calculate(root_entries)

        # 5. Calculate participant index
        participant_index = self.participant_calculator.calculate(root_entries)

        return LogbookExportData(
            entries=root_entries,
            yearly_summaries=yearly_summaries,
            participant_index=participant_index,
        )
