/**
 * Calendar event helper functions.
 *
 * Pure functions to transform DisplayJournal arrays into CalendarEvent
 * objects suitable for month and agenda calendar views.
 * These helpers ensure alternate calendar views reuse the canonical
 * journal/event contracts without forking event semantics.
 */

import {
  format,
  subDays,
  addDays,
  endOfMonth,
  startOfMonth,
  startOfWeek,
  endOfWeek,
  parseISO,
  eachDayOfInterval,
} from 'date-fns';
import { DisplayJournal } from '@/utils/journalTransformers';
import { JournalType, EventState, CalendarInfoData } from '@/types/journals';

/**
 * A calendar event derived from a DisplayJournal.
 * Used by CalendarMonthView and CalendarAgendaView for rendering.
 */
export interface CalendarEvent {
  /** Journal ID — used for navigation links */
  id: string;
  /** Journal title */
  title: string;
  /** Display date in YYYY-MM-DD format (local) — start of the event */
  date: string;
  /** End date in YYYY-MM-DD format (local) — same as date for single-day events */
  endDate: string;
  /** Whether this event spans multiple days */
  isMultiDay: boolean;
  /** Start time as HH:MM, or null for all-day / non-event journals */
  startTime: string | null;
  /** End time as HH:MM, or null for all-day / non-event journals */
  endTime: string | null;
  /** Whether this is an all-day event */
  isAllDay: boolean;
  /** Calendar colour for visual coding (hex string) */
  calendarColor: string;
  /** Calendar name for tooltip / screen readers */
  calendarName?: string;
  /** Event state (invited, tentative, confirmed, cancelled) */
  eventState?: EventState;
  /** Whether the event is cancelled */
  isCancelled: boolean;
  /** Journal types (for type icon rendering) */
  journalTypes: JournalType[];
  /** Whether the journal has pending reviews */
  hasPendingReviews: boolean;
  /** Whether the event is synced to Google Calendar */
  isSyncedToGoogle: boolean;
}

const DEFAULT_CALENDAR_COLOR = '#6b7280';

/**
 * Extract the HH:MM portion from an HH:MM:SS time string.
 */
function formatTimeShort(time: string | null | undefined): string | null {
  if (!time) return null;
  // Handle HH:MM:SS or HH:MM format
  const parts = time.split(':');
  if (parts.length >= 2) {
    return `${parts[0]}:${parts[1]}`;
  }
  return null;
}

/**
 * Extract CalendarInfoData from a DisplayJournal's type_data.
 */
function getCalendarInfo(
  journal: DisplayJournal
): CalendarInfoData | undefined {
  return journal.type_data?.event as CalendarInfoData | undefined;
}

/**
 * Convert a DisplayJournal into a CalendarEvent for calendar views.
 */
export function toCalendarEvent(journal: DisplayJournal): CalendarEvent {
  const calendarInfo = getCalendarInfo(journal);

  const isAllDay = calendarInfo?.is_all_day ?? true;
  const startTime = formatTimeShort(calendarInfo?.start_time);
  const endTime = formatTimeShort(calendarInfo?.end_time);
  const eventState = calendarInfo?.event_state;
  const isCancelled = eventState === EventState.CANCELLED;

  // Extract the date portions from the event_date_range
  const dateStr = journal.event_date_range.start;
  const endDateStr = journal.event_date_range.end;
  const localDate = format(parseISO(dateStr), 'yyyy-MM-dd');
  const localEndDate = format(parseISO(endDateStr), 'yyyy-MM-dd');
  const isMultiDay = localDate !== localEndDate;

  return {
    id: journal.id,
    title: journal.title,
    date: localDate,
    endDate: localEndDate,
    isMultiDay,
    startTime,
    endTime,
    isAllDay,
    calendarColor: journal.calendar?.color || DEFAULT_CALENDAR_COLOR,
    calendarName: journal.calendar?.name,
    eventState,
    isCancelled,
    journalTypes: journal.types,
    hasPendingReviews: journal.has_pending_reviews ?? false,
    isSyncedToGoogle: journal.calendar?.is_synced_to_google ?? false,
  };
}

/**
 * Batch conversion of DisplayJournals to CalendarEvents.
 */
export function toCalendarEvents(journals: DisplayJournal[]): CalendarEvent[] {
  return journals.map(toCalendarEvent);
}

/**
 * Group calendar events into date buckets keyed by YYYY-MM-DD.
 * Events are placed in the bucket matching their `date` field.
 */
export function groupEventsByDate(
  events: CalendarEvent[]
): Record<string, CalendarEvent[]> {
  const grouped: Record<string, CalendarEvent[]> = {};

  for (const event of events) {
    if (event.isMultiDay && event.endDate && event.endDate !== event.date) {
      // Multiday events: place into every date bucket they span
      const days = eachDayOfInterval({
        start: parseISO(event.date),
        end: parseISO(event.endDate),
      });
      for (const day of days) {
        const dayKey = format(day, 'yyyy-MM-dd');
        if (!grouped[dayKey]) {
          grouped[dayKey] = [];
        }
        grouped[dayKey].push(event);
      }
    } else {
      // Single-day events: place into their date bucket
      if (!grouped[event.date]) {
        grouped[event.date] = [];
      }
      grouped[event.date].push(event);
    }
  }

  return grouped;
}

/**
 * Get the date range (YYYY-MM-DD strings) for a calendar month.
 * @param year - Full year (e.g. 2026)
 * @param month - 0-indexed month (0 = January, 11 = December)
 */
export function getMonthDateRange(
  year: number,
  month: number
): { start: string; end: string } {
  const monthStart = startOfMonth(new Date(year, month, 1));
  const monthEnd = endOfMonth(new Date(year, month, 1));

  const gridStart = startOfWeek(monthStart, { weekStartsOn: 1 });
  const gridEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });

  return {
    start: format(gridStart, 'yyyy-MM-dd'),
    end: format(gridEnd, 'yyyy-MM-dd'),
  };
}

/**
 * Get the date range for an agenda view centered on an anchor date.
 * @param anchorDate - The center date for the agenda window
 * @param daysForward - Number of days to include after the anchor
 * @param daysBack - Number of days to include before the anchor
 */
export function getAgendaDateRange(
  anchorDate: Date,
  daysForward: number,
  daysBack: number
): { start: string; end: string } {
  const start = subDays(anchorDate, daysBack);
  const end = addDays(anchorDate, daysForward);

  return {
    start: format(start, 'yyyy-MM-dd'),
    end: format(end, 'yyyy-MM-dd'),
  };
}

/**
 * Get the date range for a calendar week view (Mon-Sun).
 * @param date - Any date within the target week
 */
export function getWeekDateRange(date: Date): { start: string; end: string } {
  const start = startOfWeek(date, { weekStartsOn: 1 });
  const end = endOfWeek(date, { weekStartsOn: 1 });

  return {
    start: format(start, 'yyyy-MM-dd'),
    end: format(end, 'yyyy-MM-dd'),
  };
}

/**
 * Get the date range for a single day view.
 * @param date - The target date
 */
export function getDayDateRange(date: Date): { start: string; end: string } {
  const dateStr = format(date, 'yyyy-MM-dd');
  return {
    start: dateStr,
    end: dateStr,
  };
}
