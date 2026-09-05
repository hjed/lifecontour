/**
 * Tests for date utility functions.
 */

import {
  formatDateOnly,
  formatDateRange,
  formatIsoDate,
  formatIsoDateLong,
  formatIsoWeekdayDate,
  isIsoCalendarDate,
} from '../date-utils';

describe('formatDateOnly', () => {
  it('formats a date as YYYY-MM-DD', () => {
    const date = new Date(2024, 0, 15); // January 15, 2024
    expect(formatDateOnly(date)).toBe('2024-01-15');
  });

  it('pads single-digit months and days with zeros', () => {
    const date = new Date(2024, 0, 5); // January 5, 2024
    expect(formatDateOnly(date)).toBe('2024-01-05');
  });

  it('handles December correctly', () => {
    const date = new Date(2024, 11, 31); // December 31, 2024
    expect(formatDateOnly(date)).toBe('2024-12-31');
  });

  it('uses local timezone, not UTC', () => {
    // Create a date at 11 PM local time
    const date = new Date(2024, 0, 15, 23, 0, 0);
    // Should still be Jan 15 in local timezone
    expect(formatDateOnly(date)).toBe('2024-01-15');
    // toISOString() might show Jan 16 if UTC is ahead
  });
});

describe('formatDateRange', () => {
  it('formats same-day range as single date', () => {
    const result = formatDateRange('2024-01-15', '2024-01-15');
    expect(result).toBe('15 Jan 2024');
  });

  it('formats same-month range with abbreviated format', () => {
    const result = formatDateRange('2024-01-15', '2024-01-20');
    expect(result).toBe('15 - 20 Jan 2024');
  });

  it('formats different-month range with full dates', () => {
    const result = formatDateRange('2024-01-15', '2024-02-20');
    expect(result).toBe('15 Jan 2024 - 20 Feb 2024');
  });

  it('formats different-year range with full dates', () => {
    const result = formatDateRange('2024-12-15', '2025-01-20');
    expect(result).toBe('15 Dec 2024 - 20 Jan 2025');
  });

  it('accepts Date objects as input', () => {
    const start = new Date(2024, 0, 15);
    const end = new Date(2024, 0, 20);
    const result = formatDateRange(start, end);
    expect(result).toBe('15 - 20 Jan 2024');
  });

  it('accepts mixed string and Date inputs', () => {
    const start = '2024-01-15';
    const end = new Date(2024, 0, 20);
    const result = formatDateRange(start, end);
    expect(result).toBe('15 - 20 Jan 2024');
  });

  it('handles end of month correctly', () => {
    const result = formatDateRange('2024-01-31', '2024-02-01');
    expect(result).toBe('31 Jan 2024 - 1 Feb 2024');
  });

  it('handles leap year correctly', () => {
    const result = formatDateRange('2024-02-28', '2024-02-29');
    expect(result).toBe('28 - 29 Feb 2024');
  });
});

describe('formatIsoDate', () => {
  it('writes an ISO calendar date the way the rest of the app writes dates', () => {
    expect(formatIsoDate('2026-09-01')).toBe('1 Sep 2026');
  });

  /**
   * Its whole reason to exist, and the reason `formatDateRange` cannot be used
   * for this: `new Date('2026-01-01')` is parsed as UTC midnight, so in any
   * zone behind UTC it formats as the previous day. A date already resolved in
   * the user's timezone must not be shifted a second time.
   */
  it('does not shift a date that has already been resolved', () => {
    expect(formatIsoDate('2026-01-01')).toBe('1 Jan 2026');
    expect(formatIsoDate('2026-12-31')).toBe('31 Dec 2026');
  });
});

describe('formatIsoDateLong', () => {
  it('writes the full localised date the dashboard header carries', () => {
    // W2's form: weekday, then day before month, en-AU throughout.
    expect(formatIsoDateLong('2026-07-29')).toBe('Wednesday, 29 July 2026');
  });

  /**
   * Same contract as {@link formatIsoDate}, and it matters more here: the
   * dashboard's date is the server's anchor, already resolved in the user's
   * configured zone. Parsing it as an instant would shift it a day in any zone
   * behind UTC and label the page with yesterday.
   */
  it('does not shift a date that has already been resolved', () => {
    expect(formatIsoDateLong('2026-01-01')).toBe('Thursday, 1 January 2026');
    expect(formatIsoDateLong('2026-12-31')).toBe('Thursday, 31 December 2026');
  });

  it('handles a leap day', () => {
    expect(formatIsoDateLong('2024-02-29')).toBe('Thursday, 29 February 2024');
  });
});

describe('formatIsoWeekdayDate', () => {
  it('writes the weekday and day-month the tomorrow disclosure labels itself with', () => {
    // W19's form: "Tomorrow — <weekday>, <d Month>". The year is not drawn,
    // because a disclosure about tomorrow is never about another year than
    // the one the page already names in its header.
    expect(formatIsoWeekdayDate('2026-08-01')).toBe('Saturday, 1 August');
  });

  /**
   * The same contract as {@link formatIsoDateLong}, and it matters for the
   * same reason: `agenda.tomorrow.date` is the *server's* local tomorrow,
   * already resolved in the user's configured zone. Parsing it as an instant
   * would shift it back a day in any zone behind UTC and label the row with
   * today.
   */
  it('does not shift a date that has already been resolved', () => {
    expect(formatIsoWeekdayDate('2026-01-01')).toBe('Thursday, 1 January');
    expect(formatIsoWeekdayDate('2026-12-31')).toBe('Thursday, 31 December');
  });

  it('handles a leap day', () => {
    expect(formatIsoWeekdayDate('2024-02-29')).toBe('Thursday, 29 February');
  });
});

describe('isIsoCalendarDate', () => {
  it('accepts an ISO calendar date', () => {
    expect(isIsoCalendarDate('2026-08-01')).toBe(true);
    expect(isIsoCalendarDate('2024-02-29')).toBe(true);
  });

  /**
   * Everything a caller's types promised and its payload did not deliver.
   * These fail identically from the formatter's seat — `format(parseISO(x))`
   * throws a RangeError — so the guard answers them identically too.
   */
  it.each([
    ['an empty string', ''],
    ['a word', 'tomorrow'],
    ['a day that does not exist', '2026-02-31'],
    ['undefined', undefined],
    ['null', null],
    ['a number', 20260801],
    ['an object', { date: '2026-08-01' }],
  ])('rejects %s', (_, value) => {
    expect(isIsoCalendarDate(value)).toBe(false);
  });

  /**
   * The rejections that matter most, because `parseISO` accepts all three and
   * each would then be formatted in the *browser's* zone. An instant is the
   * dangerous one: anywhere behind UTC it labels its caller with the previous
   * calendar day, which is the exact failure the calendar-date helpers exist
   * to avoid.
   */
  it.each([
    ['an instant', '2026-08-01T00:00:00Z'],
    ['an instant with an offset', '2026-08-01T00:00:00+10:00'],
    ['a year and month only', '2026-08'],
    ['a basic-format date', '20260801'],
  ])('rejects %s, which parseISO would otherwise accept', (_, value) => {
    expect(isIsoCalendarDate(value)).toBe(false);
  });
});
