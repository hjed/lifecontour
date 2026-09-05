/**
 * Date utility functions for the application.
 *
 * Provides consistent date formatting and manipulation across the app,
 * with proper timezone handling and Australian locale support.
 */

import { format, isValid, parseISO } from 'date-fns';
import { enAU } from 'date-fns/locale';

/**
 * Format a Date object as YYYY-MM-DD in local timezone.
 *
 * This avoids timezone issues that occur when using toISOString(),
 * which converts to UTC and can shift the date for users outside UTC.
 *
 * @param date - The date to format
 * @returns Date string in YYYY-MM-DD format
 *
 * @example
 * formatDateOnly(new Date(2024, 0, 15)) // "2024-01-15"
 */
export function formatDateOnly(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Format a date range for display with smart formatting.
 *
 * - Same day: "15 Jan 2024"
 * - Same month: "15 - 20 Jan 2024"
 * - Different months: "15 Jan 2024 - 20 Feb 2024"
 *
 * @param start - Start date (ISO string or Date)
 * @param end - End date (ISO string or Date)
 * @returns Formatted date range string
 *
 * @example
 * formatDateRange("2024-01-15", "2024-01-15") // "15 Jan 2024"
 * formatDateRange("2024-01-15", "2024-01-20") // "15 - 20 Jan 2024"
 * formatDateRange("2024-01-15", "2024-02-20") // "15 Jan 2024 - 20 Feb 2024"
 */
export function formatDateRange(
  start: string | Date,
  end: string | Date
): string {
  const startDate = typeof start === 'string' ? new Date(start) : start;
  const endDate = typeof end === 'string' ? new Date(end) : end;

  // If same day, show single date
  if (format(startDate, 'yyyy-MM-dd') === format(endDate, 'yyyy-MM-dd')) {
    return format(startDate, 'd MMM yyyy', { locale: enAU });
  }

  // If same month and year, show abbreviated format
  if (format(startDate, 'yyyy-MM') === format(endDate, 'yyyy-MM')) {
    return `${format(startDate, 'd', { locale: enAU })} - ${format(endDate, 'd MMM yyyy', { locale: enAU })}`;
  }

  // Different months, show full range
  return `${format(startDate, 'd MMM yyyy', { locale: enAU })} - ${format(endDate, 'd MMM yyyy', { locale: enAU })}`;
}

/**
 * Format an ISO **calendar date** (`YYYY-MM-DD`) as `d MMM yyyy`.
 *
 * Distinct from {@link formatDateRange}, which takes instants: `new
 * Date('2026-09-01')` is parsed as UTC midnight, so in any zone behind UTC it
 * formats as the previous day. A date that has already been resolved in the
 * user's timezone must not be shifted again, so this parses it as local.
 *
 * @example formatIsoDate('2026-09-01') // "1 Sep 2026"
 */
export function formatIsoDate(date: string): string {
  return format(parseISO(date), 'd MMM yyyy', { locale: enAU });
}

/**
 * Format an ISO **calendar date** (`YYYY-MM-DD`) in full: `EEEE, d MMMM yyyy`.
 *
 * The long form the home dashboard's header carries (**W2**) —
 * *"Wednesday, 29 July 2026"*. Parsed as a local calendar date for the same
 * reason as {@link formatIsoDate}, and it matters more here: the dashboard's
 * date is the server's anchor, already resolved in the user's configured zone.
 * Re-parsing it as an instant would shift it a day in any zone behind UTC and
 * label the page with yesterday.
 *
 * @example formatIsoDateLong('2026-07-29') // "Wednesday, 29 July 2026"
 */
export function formatIsoDateLong(date: string): string {
  return format(parseISO(date), 'EEEE, d MMMM yyyy', { locale: enAU });
}

/**
 * Format an ISO **calendar date** (`YYYY-MM-DD`) as `EEEE, d MMMM` — no year.
 *
 * The form the agenda's tomorrow disclosure labels itself with (**W19**) —
 * *"Saturday, 1 August"*, written after the word *Tomorrow*. The year is left
 * off deliberately: the row is always about the day after the one the page
 * header already names in full, so repeating it adds nothing.
 *
 * Parsed as a local calendar date for the same reason as
 * {@link formatIsoDateLong}: `agenda.tomorrow.date` is the server's local
 * tomorrow, already resolved in the user's configured zone, and re-parsing it
 * as an instant would shift it back a day in any zone behind UTC — labelling
 * the row with today.
 *
 * @example formatIsoWeekdayDate('2026-08-01') // "Saturday, 1 August"
 */
export function formatIsoWeekdayDate(date: string): string {
  return format(parseISO(date), 'EEEE, d MMMM', { locale: enAU });
}

/** `YYYY-MM-DD` and nothing else — not an instant, not a partial date. */
const ISO_CALENDAR_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Is `value` an ISO **calendar date** (`YYYY-MM-DD`) a formatter can read?
 *
 * Presence, type, shape and parseability in one question, for a caller holding
 * a value its types promise but its payload might not deliver. `''`, `null`,
 * `'tomorrow'` and `'2026-02-31'` are all answered the same way, because from
 * the formatter's seat they fail identically: `format(parseISO(...))` throws a
 * `RangeError` on an invalid date and takes the render down with it.
 *
 * **The shape is checked, not just the parse, and that is the point of the
 * guard rather than a nicety.** `parseISO` is generous — it accepts
 * `2026-08-01T00:00:00Z`, `20260801` and even `2026-08` — and an *instant*
 * that survives this check would then be formatted in the **browser's** zone,
 * labelling a caller with the previous calendar day anywhere behind UTC. That
 * is the precise failure {@link formatIsoWeekdayDate} and
 * {@link formatIsoDateLong} exist to avoid, so a value that is not a bare
 * calendar date is rejected rather than quietly re-anchored.
 *
 * Written as a type guard so a caller that asks this can then use the value.
 */
export function isIsoCalendarDate(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    ISO_CALENDAR_DATE.test(value) &&
    isValid(parseISO(value))
  );
}
