/**
 * When the home dashboard's anchor day ends.
 *
 * The dashboard is read for **one day** — the server's today in the user's
 * configured timezone, echoed as `meta.anchor` — and every window on the page
 * hangs off it. The query has one fixed key and a five-minute `staleTime`, and
 * React Query refetches on staleness only when something asks, so a dashboard
 * left open *and focused* across local midnight keeps yesterday's anchor and
 * yesterday's date in the **W2** header. `refetchOnWindowFocus` corrects it the
 * moment the tab is returned to; an always-visible dashboard is the exposure
 * this closes.
 *
 * **The refresh is scheduled for a boundary, not on an interval.** A fixed
 * interval would refetch a page nobody is watching all day and still arrive
 * late at the one moment that matters. The boundary is midnight in the
 * anchor's own zone, which is the same zone the server resolved the day in —
 * the browser's midnight is a different instant for anyone whose configured
 * zone is not their machine's.
 *
 * **The arithmetic is `zonedMidnight`'s, not a fresh copy of it.** Working out
 * when a calendar day starts in a named zone is the write half of the
 * `event_date_range` convention and is already pinned there against Sydney's
 * spring-forward, Santiago's skipped midnight and Apia's skipped day. Adding
 * twenty-four hours to the anchor day's own midnight is the tempting version
 * and it is wrong twice a year: an hour late going into DST, an hour early
 * coming out.
 */

import { isIsoCalendarDate, zonedMidnight } from '@/lib/date-utils';
import type { HomeDashboardAnchor } from '@/lib/api/home-dashboard';

/**
 * How long until the anchor day ends, in milliseconds.
 *
 * Zero or negative means it already has — a payload cached across midnight —
 * and the caller should refresh at once. `null` means the anchor cannot be
 * read at all and **nothing should be scheduled**: the arithmetic would be
 * `NaN`, and `setTimeout(NaN)` fires immediately rather than never.
 *
 * The answer is **not** clamped to what a `setTimeout` can hold. How long a
 * timer can wait is the scheduler's problem, and clamping here made it look
 * solved when it was not: a boundary further off than ~24.8 days — a browser
 * clock weeks behind, or an anchor the server should never send — would fire
 * the timer early, and `useAnchorDayRefresh` would not re-arm because its
 * effect is keyed on an anchor the refetch did not change. The page would then
 * have *no* timer at all. The hook sleeps in instalments instead.
 *
 * @param anchor The payload's own `meta.anchor`: the day, and the zone it was
 *   resolved in.
 * @param now Defaults to the current instant; passed in by tests.
 */
export function msUntilNextAnchorDay(
  anchor: HomeDashboardAnchor,
  now: Date = new Date()
): number | null {
  if (!isIsoCalendarDate(anchor.date)) {
    return null;
  }

  const [year, month, day] = anchor.date.split('-').map(Number);
  // A picker date — only its local calendar parts are read, never its clock —
  // and `Date` normalises the overflow, so the 31st rolls into the 1st.
  const nextDay = new Date(year, month - 1, day + 1);

  const boundary = zonedMidnight(nextDay, anchor.timezone).getTime();
  if (!Number.isFinite(boundary)) {
    return null;
  }

  return boundary - now.getTime();
}
