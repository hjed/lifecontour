import { format, parseISO, eachDayOfInterval, isAfter } from 'date-fns';
import { DisplayJournal } from '@/utils/journalTransformers';

export interface JournalDayGroup {
  date: string; // ISO date format YYYY-MM-DD
  journals: DisplayJournal[];
  isEmpty: boolean;
}

export interface GroupJournalsOptions {
  journals: DisplayJournal[];
  startDate: string; // YYYY-MM-DD
  endDate: string; // YYYY-MM-DD
  collapseEmpty: boolean;
}

/**
 * Groups an array of journals into a contiguous array of days between startDate and endDate.
 * Journals outside the specified start/end date will be placed into dynamically created ad-hoc buckets to prevent data loss.
 * Sorts days continuously descending (Newest at top, oldest at bottom).
 * Sorts journals within each day continuously ascending (Oldest journal first chronologically on that day).
 */
export function groupJournalsByDay({
  journals,
  startDate,
  endDate,
  collapseEmpty,
}: GroupJournalsOptions): JournalDayGroup[] {
  const start = parseISO(startDate);
  const end = parseISO(endDate);

  if (isAfter(start, end)) {
    return [];
  }

  // Create contiguous days array
  const days = eachDayOfInterval({ start, end });

  // Initialize a map for quick lookup
  const dayGroupsMap: Record<string, JournalDayGroup> = {};

  days.forEach(day => {
    const formattedDate = format(day, 'yyyy-MM-dd');
    dayGroupsMap[formattedDate] = {
      date: formattedDate,
      journals: [],
      isEmpty: true,
    };
  });

  // Group journals
  journals.forEach(journal => {
    // Determine the local date string from original timestamp using parseISO to prevent unintended UTC shifting
    const dateValue = parseISO(journal.event_date_range.start);
    const formattedDate = format(dateValue, 'yyyy-MM-dd');

    if (dayGroupsMap[formattedDate]) {
      dayGroupsMap[formattedDate].journals.push(journal);
      dayGroupsMap[formattedDate].isEmpty = false;
    } else {
      // Out of bounds bucket creation
      dayGroupsMap[formattedDate] = {
        date: formattedDate,
        journals: [journal],
        isEmpty: false,
      };
    }
  });

  // Sort journals within each day by event_date_range.start ascending (chronological).
  Object.values(dayGroupsMap).forEach(group => {
    group.journals.sort((a, b) => {
      return (
        parseISO(a.event_date_range.start).getTime() -
        parseISO(b.event_date_range.start).getTime()
      );
    });
  });

  // Sort days DESCENDING (Newest day first)
  const resultKeys = Object.keys(dayGroupsMap).sort((a, b) =>
    b.localeCompare(a)
  );

  let result = resultKeys.map(k => dayGroupsMap[k]);

  if (collapseEmpty) {
    result = result.filter(group => !group.isEmpty);
  }

  return result;
}
