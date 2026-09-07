/**
 * Tests for date utility functions.
 */

import {
  formatDateOnly,
  formatDateRange,
  formatIsoDate,
  formatIsoDateLong,
  formatIsoShortWeekdayDate,
  formatIsoWeekdayDate,
  isIsoCalendarDate,
  localDateIn,
  zonedCalendarDay,
  zonedMidnight,
} from '../date-utils';

const SYDNEY = 'Australia/Sydney';
const NEW_YORK = 'America/New_York';
const SANTIAGO = 'America/Santiago';
const APIA = 'Pacific/Apia';

/**
 * A calendar day as react-day-picker hands one over: browser-local midnight,
 * whatever the ambient zone happens to be.
 */
function pickerDay(isoDate: string): Date {
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, day);
}

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

describe('formatIsoShortWeekdayDate', () => {
  it('writes the short absolute form the due chip falls back to', () => {
    // W25's third case: `Today`, `Tomorrow`, then a short absolute form —
    // "Sat 1 Aug". A chip sits at the end of a row that already carries the
    // task's text, so it is abbreviated where the tomorrow disclosure's label
    // (W19) is written out in full.
    expect(formatIsoShortWeekdayDate('2026-08-01')).toBe('Sat 1 Aug');
  });

  it('does not carry a year', () => {
    // The whole window is seven days from the anchor the page header already
    // names in full, so a year on a chip would be noise in every case it
    // could appear.
    expect(formatIsoShortWeekdayDate('2026-08-05')).toBe('Wed 5 Aug');
  });

  /**
   * The same contract as {@link formatIsoWeekdayDate}, and load-bearing for
   * the same reason: `due_journal.date` is a calendar day the *server*
   * resolved in the user's configured zone. Parsed as an instant it would
   * shift back a day in any zone behind UTC and name the wrong weekday.
   */
  it('does not shift a date that has already been resolved', () => {
    expect(formatIsoShortWeekdayDate('2026-01-01')).toBe('Thu 1 Jan');
    expect(formatIsoShortWeekdayDate('2026-12-31')).toBe('Thu 31 Dec');
  });

  it('handles a leap day', () => {
    expect(formatIsoShortWeekdayDate('2024-02-29')).toBe('Thu 29 Feb');
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

/**
 * `zonedMidnight` and `zonedCalendarDay` are the two halves of the
 * `event_date_range` convention, and they only work as a pair: a bound is
 * stored as the UTC instant of midnight on a calendar day *in a named zone*,
 * so the zone that resolves the day on the way out has to be the one that
 * anchors it on the way back in. Anchoring on the browser's zone instead — as
 * the `localMidnight` these replace did — moves an untouched range a calendar
 * day whenever the browser is somewhere the user is not (issue #1401).
 *
 * Every case names its zone, so all of them hold in any ambient zone.
 */
describe('zonedMidnight', () => {
  it.each([
    ['a zone ahead of UTC', '2026-09-05', SYDNEY, '2026-09-04T14:00:00.000Z'],
    ['a zone behind UTC', '2025-01-15', NEW_YORK, '2025-01-15T05:00:00.000Z'],
  ])('anchors midnight in %s', (_, day, zone, expected) => {
    expect(zonedMidnight(pickerDay(day), zone).toISOString()).toBe(expected);
  });

  it.each([
    // Either side of the transition, where the offset at UTC midnight is
    // already the offset the day starts on: the control the two transition
    // days below are read against.
    ['before the spring transition', '2025-03-08', '2025-03-08T05:00:00.000Z'],
    ['after the spring transition', '2025-03-10', '2025-03-10T04:00:00.000Z'],
    // Daylight saving starts at 02:00 on this day: midnight is still EST.
    ['on the spring transition day', '2025-03-09', '2025-03-09T05:00:00.000Z'],
    // ...and ends at 02:00 on this one, so midnight is still EDT.
    ['on the autumn transition day', '2025-11-02', '2025-11-02T04:00:00.000Z'],
  ])('reads the offset the day actually starts on, %s', (_, day, expected) => {
    expect(zonedMidnight(pickerDay(day), NEW_YORK).toISOString()).toBe(
      expected
    );
  });

  it('uses the offset in force at midnight, not the one later that day', () => {
    // Sydney puts the clocks forward at 02:00 on 4 October 2026, so the day
    // *starts* at +10:00 and ends at +11:00. Probing the zone at UTC midnight
    // sees +11:00 — the offset the day ends on — and a single probe would
    // write 13:00Z, which is 23:00 on 3 October: the previous day.
    expect(zonedMidnight(pickerDay('2026-10-04'), SYDNEY).toISOString()).toBe(
      '2026-10-03T14:00:00.000Z'
    );
  });

  it('clamps to the start of a day whose midnight does not exist', () => {
    // Santiago puts the clocks forward at 24:00, so 7 September 2025 has no
    // 00:00 at all and begins at 01:00. The answer has to be that instant:
    // correcting onto the offset either side of the gap would land on 6
    // September, which is not the day the user picked.
    expect(zonedMidnight(pickerDay('2025-09-07'), SANTIAGO).toISOString()).toBe(
      '2025-09-07T04:00:00.000Z'
    );
  });

  it('clamps a wholly skipped calendar day forward, never backward', () => {
    // Samoa crossed the date line at the end of 2011: 30 December simply did
    // not happen there. No answer is right, so the rule is the same one the
    // Santiago gap follows — the first instant that does exist, which is the
    // *following* day. Landing on the 29th instead would silently date an
    // event a day earlier than the one that was picked.
    const skipped = zonedMidnight(pickerDay('2011-12-30'), APIA);

    expect(skipped.toISOString()).toBe('2011-12-30T10:00:00.000Z');
    expect(localDateIn(APIA, skipped)).toBe('2011-12-31');
  });

  it('still resolves the days either side of a skipped one', () => {
    expect(
      localDateIn(APIA, zonedMidnight(pickerDay('2011-12-29'), APIA))
    ).toBe('2011-12-29');
    expect(
      localDateIn(APIA, zonedMidnight(pickerDay('2011-12-31'), APIA))
    ).toBe('2011-12-31');
  });

  it('takes the calendar day from the picked date, not its clock', () => {
    // react-day-picker hands back whatever instant the selected cell carries.
    const afternoon = new Date(2025, 0, 15, 16, 42, 9, 128);

    expect(zonedMidnight(afternoon, NEW_YORK).toISOString()).toBe(
      '2025-01-15T05:00:00.000Z'
    );
  });

  it('falls back to browser-local midnight for a zone it cannot resolve', () => {
    // A stale cached timezone should cost the user the anchor, not the save.
    const day = pickerDay('2025-01-15');

    expect(zonedMidnight(day, 'Not/A_Zone').toISOString()).toBe(
      new Date(2025, 0, 15).toISOString()
    );
  });

  it('does not mutate the date it is given', () => {
    const original = new Date(2025, 0, 15, 9, 15);

    zonedMidnight(original, SYDNEY);

    expect(original.getHours()).toBe(9);
  });
});

/**
 * The read half: which calendar day a stored instant belongs to depends
 * entirely on who is asking, which is the whole of issue #1401 in one line.
 */
describe('zonedCalendarDay', () => {
  it.each([
    ['New York, where it is still the evening before', NEW_YORK, '2025-01-14'],
    ['Sydney, where the morning is already under way', SYDNEY, '2025-01-15'],
  ])('resolves the same instant to its own day in %s', (_, zone, expected) => {
    const day = zonedCalendarDay('2025-01-15T00:00:00.000Z', zone);

    expect(formatDateOnly(day)).toBe(expected);
  });

  it('returns the day at browser-local midnight, as a picker reads it', () => {
    const day = zonedCalendarDay('2025-01-15T05:00:00.000Z', NEW_YORK);

    expect([day.getHours(), day.getMinutes(), day.getSeconds()]).toEqual([
      0, 0, 0,
    ]);
  });

  it('accepts an instant that is already a Date', () => {
    const day = zonedCalendarDay(new Date('2025-01-15T05:00:00.000Z'), SYDNEY);

    expect(formatDateOnly(day)).toBe('2025-01-15');
  });

  it('falls back to the browser day for a zone it cannot resolve', () => {
    const instant = '2025-01-15T05:00:00.000Z';

    expect(formatDateOnly(zonedCalendarDay(instant, 'Not/A_Zone'))).toBe(
      formatDateOnly(new Date(instant))
    );
  });

  it.each([
    ['ahead of UTC', SYDNEY, '2026-09-04T14:00:00.000Z'],
    ['behind UTC', NEW_YORK, '2025-01-15T05:00:00.000Z'],
    ['on a transition day', SYDNEY, '2026-10-03T14:00:00.000Z'],
  ])('round-trips a correctly stored bound %s untouched', (_, zone, stored) => {
    const reopened = zonedCalendarDay(stored, zone);

    expect(zonedMidnight(reopened, zone).toISOString()).toBe(stored);
  });
});
