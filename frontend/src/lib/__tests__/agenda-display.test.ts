/**
 * The agenda row's clock text (**W13**): `HH:MM – HH:MM`, from the clock
 * values the payload carries in the event's own zone.
 */

import { formatClockRange, formatEventCount } from '../agenda-display';

describe('formatClockRange', () => {
  it('renders a start and end as HH:MM – HH:MM, dropping the seconds', () => {
    expect(formatClockRange('09:00:00', '10:30:00')).toBe('09:00 – 10:30');
  });

  it('passes HH:MM values through unchanged', () => {
    expect(formatClockRange('14:00', '15:00')).toBe('14:00 – 15:00');
  });

  it('shows the start alone when there is no end', () => {
    expect(formatClockRange('09:00:00', null)).toBe('09:00');
  });

  it('is null when there is no start, whatever the end says', () => {
    expect(formatClockRange(null, '10:00:00')).toBeNull();
    expect(formatClockRange(null, null)).toBeNull();
  });

  it('rejects a value that is not a clock rather than rendering garbage', () => {
    expect(formatClockRange('nine', '10:00:00')).toBeNull();
  });
});

describe('formatEventCount', () => {
  it('writes the plural for more than one', () => {
    expect(formatEventCount(2)).toBe('2 events');
  });

  it('writes the singular for exactly one', () => {
    expect(formatEventCount(1)).toBe('1 event');
  });

  /**
   * Zero is drawn, not hidden: W19's row stays put when nothing is scheduled
   * tomorrow, so the count has to have something honest to say.
   */
  it('writes the plural for none', () => {
    expect(formatEventCount(0)).toBe('0 events');
  });
});
