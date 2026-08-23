/**
 * Tests for date utility functions.
 */

import { formatDateOnly, formatDateRange, formatIsoDate } from '../date-utils';

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
