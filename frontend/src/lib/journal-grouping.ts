import {
  format,
  parseISO,
  eachDayOfInterval,
  isAfter,
  isBefore,
} from 'date-fns';
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
 * Sorts days continuously ascending (Oldest at top, newest at bottom).
 * Sorts journals within each day continuously ascending (Oldest journal first chronologically on that day).
 */
export function groupJournalsByDay({
  journals,
  startDate,
  endDate,
  collapseEmpty,
}: GroupJournalsOptions): JournalDayGroup[] {
  let start = parseISO(startDate);
  let end = parseISO(endDate);

  // Dynamically expand interval to prevent non-contiguous out-of-bounds keys
  journals.forEach(journal => {
    const journalDate = parseISO(journal.event_date_range.start);
    if (isBefore(journalDate, start)) start = journalDate;
    if (isAfter(journalDate, end)) end = journalDate;
  });

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

  // Sort days ASCENDING (Oldest day first)
  const resultKeys = Object.keys(dayGroupsMap).sort((a, b) =>
    a.localeCompare(b)
  );

  let result = resultKeys.map(k => dayGroupsMap[k]);

  if (collapseEmpty) {
    result = result.filter(group => !group.isEmpty);
  }

  return result;
}
