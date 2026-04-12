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
  parseISO,
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
  /** Display date in YYYY-MM-DD format (local) */
  date: string;
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

  // Extract the date portion from the event_date_range start
  const dateStr = journal.event_date_range.start;
  const localDate = format(parseISO(dateStr), 'yyyy-MM-dd');

  return {
    id: journal.id,
    title: journal.title,
    date: localDate,
    startTime,
    endTime,
    isAllDay,
    calendarColor: journal.calendar?.color || DEFAULT_CALENDAR_COLOR,
    calendarName: journal.calendar?.name,
    eventState,
    isCancelled,
    journalTypes: journal.types,
    hasPendingReviews: journal.has_pending_reviews ?? false,
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
    if (!grouped[event.date]) {
      grouped[event.date] = [];
    }
    grouped[event.date].push(event);
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

  return {
    start: format(monthStart, 'yyyy-MM-dd'),
    end: format(monthEnd, 'yyyy-MM-dd'),
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
