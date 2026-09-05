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
 * The parts of `instant`'s wall clock in `timezone`, `en-US` only for its
 * stable part *names* — the values are read individually, never its layout.
 */
function zoneParts(
  timezone: string | undefined,
  instant: Date
): Intl.DateTimeFormatPart[] {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(instant);
}

function partValue(
  parts: Intl.DateTimeFormatPart[],
  type: Intl.DateTimeFormatPartTypes
): string {
  return parts.find(part => part.type === type)?.value ?? '';
}

/**
 * How far `timezone` is from UTC at `instant`, in milliseconds — positive east.
 *
 * Read from the zone's own wall clock rather than from a table, so there is no
 * tzdata of ours to fall out of date. Throws for a zone `Intl` does not know,
 * which is the caller's cue to fall back.
 *
 * `instant` is expected on a whole second; the sub-second part of the reading
 * is dropped, and every caller here works from a whole-second bound.
 */
function zoneOffsetMs(timezone: string, instant: Date): number {
  const parts = zoneParts(timezone, instant);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    Number(partValue(parts, type));

  const wallClock = Date.UTC(
    value('year'),
    value('month') - 1,
    value('day'),
    value('hour'),
    value('minute'),
    value('second')
  );
  return wallClock - (instant.getTime() - instant.getMilliseconds());
}

/**
 * The calendar date `instant` falls on in `timezone`, as `YYYY-MM-DD`.
 *
 * Assembled from `formatToParts` rather than from a locale whose numeric
 * format happens to be ISO-shaped, so the answer does not depend on which ICU
 * data the browser shipped. An unrecognised zone falls back to the browser's
 * rather than throwing: a stale cached timezone should degrade the answer, not
 * take the render down with it.
 */
export function localDateIn(timezone: string, instant: string | Date): string {
  const moment = instant instanceof Date ? instant : new Date(instant);

  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = zoneParts(timezone, moment);
  } catch {
    try {
      // An unrecognised zone: the browser's is a worse answer than the user's
      // but a far better one than none.
      parts = zoneParts(undefined, moment);
    } catch {
      // An unparseable instant, which only a malformed payload produces. `''`
      // is never greater than a real date, so a caller comparing dates leaves
      // the row out rather than filing it under a day nobody can trust.
      return '';
    }
  }

  const value = (type: Intl.DateTimeFormatPartTypes) => partValue(parts, type);
  return `${value('year')}-${value('month')}-${value('day')}`;
}

/** Today's date in `timezone` — never the browser's date, and never UTC's. */
export function todayIn(timezone: string, now?: Date): string {
  return localDateIn(timezone, now ?? new Date());
}

/**
 * The day a stored instant belongs to in `timezone`, as a **picker date**.
 *
 * The read half of the `event_date_range` convention, and the counterpart of
 * {@link zonedMidnight}. A bound is an instant, and which calendar day an
 * instant belongs to depends on who is asking: `2025-01-15T00:00Z` is the 15th
 * in Sydney and still the 14th in New York. Resolving it in the *browser's*
 * zone is what made an edited range drift a day for a user away from home
 * (issue #1401), so the zone is a parameter and the caller passes the user's
 * configured one.
 *
 * The day comes back as browser-local midnight because that is the only shape
 * react-day-picker reads: it compares a selection against a cell using local
 * date parts, so a `Date` carrying the *instant* would highlight the wrong
 * cell. The value is a calendar day wearing a `Date`, not a moment in time.
 *
 * @example
 * // In a Sydney browser, for a New York user
 * zonedCalendarDay('2025-01-15T05:00:00Z', 'America/New_York') // 15 Jan
 */
export function zonedCalendarDay(
  instant: string | Date,
  timezone: string
): Date {
  const day = localDateIn(timezone, instant);
  if (!isIsoCalendarDate(day)) {
    // `localDateIn` only answers this way for an instant it could not parse,
    // and there is no day to resolve — hand back the (invalid) date itself
    // rather than inventing one, so the caller fails where the payload did.
    return new Date(instant);
  }

  const [year, month, date] = day.split('-').map(Number);
  return new Date(year, month - 1, date);
}

/**
 * The UTC instant at which `day`'s calendar date begins in `timezone`.
 *
 * The write half of the `event_date_range` convention: a bound is stored as
 * the UTC instant of midnight on a calendar day *in a named zone*, and it must
 * be the same zone {@link zonedCalendarDay} resolved the day with or an
 * untouched range moves a day on every save (issue #1401). `day` is a picker
 * date — only its browser-local calendar parts are read, never its clock.
 *
 * The offset is probed from the zone's own wall clock rather than assumed,
 * because the offset at *UTC* midnight is not always the offset the day starts
 * on: Sydney puts its clocks forward at 02:00 on 4 October 2026, so a single
 * probe reads the offset the day *ends* on and writes 23:00 the evening
 * before. Probing again at the corrected instant settles that. Where the two
 * probes still disagree the zone has no such midnight at all — Santiago skips
 * straight from 23:59 to 01:00 — and the first candidate stands, which is the
 * first instant of the day that does exist rather than a time on the previous
 * one.
 *
 * @example
 * zonedMidnight(new Date(2026, 8, 5), 'Australia/Sydney').toISOString()
 * // "2026-09-04T14:00:00.000Z"
 */
export function zonedMidnight(day: Date, timezone: string): Date {
  const browserMidnight = new Date(
    day.getFullYear(),
    day.getMonth(),
    day.getDate()
  );

  const utcMidnight = new Date(`${formatDateOnly(day)}T00:00:00.000Z`);

  try {
    const dayEndOffset = zoneOffsetMs(timezone, utcMidnight);
    const candidate = new Date(utcMidnight.getTime() - dayEndOffset);

    const dayStartOffset = zoneOffsetMs(timezone, candidate);
    if (dayStartOffset === dayEndOffset) {
      return candidate;
    }

    const corrected = new Date(utcMidnight.getTime() - dayStartOffset);
    return zoneOffsetMs(timezone, corrected) === dayStartOffset
      ? corrected
      : candidate;
  } catch {
    // A zone `Intl` does not know — a stale cached timezone, most likely. The
    // browser's midnight is the answer this had before there was a zone to
    // anchor on, and losing the anchor should not lose the edit.
    return browserMidnight;
  }
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
