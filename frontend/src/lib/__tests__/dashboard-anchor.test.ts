/**
 * @jest-environment jsdom
 *
 * When the dashboard's anchor day ends (ITER18-004 Phase 16, inherited from
 * Phase 3).
 *
 * The query has one fixed key and a five-minute `staleTime`, and React Query
 * refetches on staleness only when something asks — so a dashboard left open
 * *and focused* across local midnight keeps yesterday's anchor, and from Phase
 * 3 on, yesterday's date in the **W2** header. Phase 3 flagged that against a
 * rule it had just written into `DashboardPageHeader`: the header shows **no**
 * date rather than guess one, because *a wrong date is worse than none*. A
 * stale anchor after midnight is that same wrong date by another route.
 *
 * **The boundary is midnight in `meta.anchor.timezone`, not a fixed interval,**
 * and every case below exists because a fixed interval or a naive twenty-four
 * hours gets one of them wrong. The assertions name the **instant** the refresh
 * is due at rather than a duration, because a duration in milliseconds hides
 * exactly the hour a DST transition moves.
 */

import { msUntilNextAnchorDay } from '../dashboard-anchor';

const SYDNEY = 'Australia/Sydney';

/** The instant `now` plus the returned delay lands on, as an ISO string. */
function dueAt(anchorDate: string, timezone: string, now: string): string {
  const delay = msUntilNextAnchorDay(
    { date: anchorDate, timezone },
    new Date(now)
  );
  if (delay === null) {
    throw new Error('expected a schedulable delay');
  }
  return new Date(new Date(now).getTime() + delay).toISOString();
}

describe('msUntilNextAnchorDay', () => {
  it('is due at the next midnight in the anchor’s own zone', () => {
    // 13:00 in Sydney on the anchor day; midnight is eleven hours away.
    expect(dueAt('2026-07-31', SYDNEY, '2026-07-31T03:00:00Z')).toBe(
      '2026-07-31T14:00:00.000Z'
    );
  });

  /**
   * The browser's midnight is a different instant from the user's whenever the
   * two zones differ, and the anchor is the server's day in the *user's* zone.
   */
  it('ignores the browser’s own day entirely', () => {
    // 22:00 UTC on 30 July is already the 31st in Sydney; the next boundary is
    // still the start of 1 August there, not of 31 July anywhere else.
    expect(dueAt('2026-07-31', SYDNEY, '2026-07-30T22:00:00Z')).toBe(
      '2026-07-31T14:00:00.000Z'
    );
  });

  /**
   * Sydney puts its clocks **forward** at 02:00 on 4 October 2026, so the day
   * that follows starts at UTC+11. Twenty-four hours after the anchor day's own
   * midnight would schedule the refresh an hour late, with the page showing
   * yesterday's date for that hour.
   */
  it('lands on the true midnight across a spring-forward boundary', () => {
    expect(dueAt('2026-10-04', SYDNEY, '2026-10-04T02:00:00Z')).toBe(
      '2026-10-04T13:00:00.000Z'
    );
  });

  /**
   * And **back** at 03:00 on 5 April 2026, so the next day starts at UTC+10.
   * The same naive arithmetic would fire an hour early, refetching a day that
   * has not started.
   */
  it('lands on the true midnight across a fall-back boundary', () => {
    expect(dueAt('2026-04-05', SYDNEY, '2026-04-05T02:00:00Z')).toBe(
      '2026-04-05T14:00:00.000Z'
    );
  });

  it('handles a UTC anchor, which is what an unset timezone resolves to', () => {
    expect(dueAt('2026-07-31', 'UTC', '2026-07-31T09:00:00Z')).toBe(
      '2026-08-01T00:00:00.000Z'
    );
  });

  /**
   * A cached payload that already crossed midnight. Due immediately is the
   * right answer, and it terminates: the hook's effect is keyed on the anchor,
   * so a refetch that returns the same anchor schedules nothing further.
   */
  it('is already due when the anchor day has passed', () => {
    const delay = msUntilNextAnchorDay(
      { date: '2026-07-30', timezone: SYDNEY },
      new Date('2026-07-31T03:00:00Z')
    );

    expect(delay).not.toBeNull();
    expect(delay).toBeLessThanOrEqual(0);
  });

  /**
   * A zone `Intl` does not know degrades to the browser's midnight rather than
   * throwing — a stale stored timezone should cost accuracy, not the refresh.
   */
  it('still answers for a timezone the browser does not recognise', () => {
    const delay = msUntilNextAnchorDay(
      { date: '2026-07-31', timezone: 'Not/AZone' },
      new Date('2026-07-31T03:00:00Z')
    );

    expect(typeof delay).toBe('number');
    expect(Number.isFinite(delay)).toBe(true);
  });

  /**
   * `null` rather than a number, and that distinction is load-bearing: an
   * unparseable anchor makes the arithmetic `NaN`, and `setTimeout(NaN)` fires
   * **immediately** — which would refetch on every render of a page whose
   * payload never gets better.
   */
  it('declines to schedule anything for an anchor it cannot read', () => {
    expect(
      msUntilNextAnchorDay(
        { date: 'not-a-date', timezone: SYDNEY },
        new Date('2026-07-31T03:00:00Z')
      )
    ).toBeNull();
  });

  it('reads the clock itself when it is not given one', () => {
    expect(
      msUntilNextAnchorDay({ date: '2026-07-31', timezone: SYDNEY })
    ).not.toBeNull();
  });
});
