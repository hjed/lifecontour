/**
 * The future-journal options a task's due journal can be set to.
 *
 * A task's due journal must be an **existing** journal dated after today in
 * the user's timezone — the specification's fifth invariant, which is why the
 * product offers no bare date picker and never creates a journal to hold a
 * task. This module turns a journal listing into the options such a picker can
 * show, and it is pure so the two rules it applies can be asserted without
 * rendering anything:
 *
 * - **Strictly after today**, mirroring the backend's `is_future_dated`. Today
 *   is not the future, so a journal starting later the same local day is not
 *   an eligible due journal.
 * - **Nearest first**, which the listing endpoint cannot be asked for. `GET
 *   /api/journals` answers `ORDER BY event_date_range_start DESC` and takes no
 *   `sort` parameter, so "recent and near-future journals first" has to be
 *   assembled from a dated window rather than requested.
 *
 * The timezone is a **parameter, not the browser's**, because the rule the
 * server applies is anchored on the user's *configured* zone. The two can
 * disagree, which is why the server's rejection is the authority and this is
 * only the convenience that keeps a doomed choice off the list.
 */

import { formatIsoDate, localDateIn, todayIn } from '@/lib/date-utils';
import { EventState, JournalType } from '@/types/journals';
import type { CalendarInfoData, JournalResource } from '@/types/journals';

/** How far ahead the unsearched picker looks. Search reaches past it. */
export const FUTURE_WINDOW_DAYS = 90;

/** One journal a task can be made due in. */
export interface FutureJournalOption {
  /** The journal's id, as a string, matching `JournalResource['id']`. */
  readonly id: string;
  readonly title: string;
  /** The journal's date in the user's timezone, `YYYY-MM-DD`. */
  readonly date: string;
  /**
   * The raw start instant, kept so journals sharing a day keep the order the
   * clock gives them rather than an arbitrary one.
   */
  readonly startsAt: string;
  /**
   * Whether this is a cancelled event journal.
   *
   * Not a reason to hide it — the user can see it everywhere else — but a task
   * made due in one is lapsed the instant it is read back, so the picker says
   * so rather than letting a resurrection resurrect nothing.
   */
  readonly cancelled: boolean;
}

/** The context a listing is judged against: whose zone, and what day it is. */
export interface FutureJournalContext {
  /** An IANA timezone, e.g. `Australia/Sydney`. */
  readonly timezone: string;
  /** Today in that timezone, `YYYY-MM-DD`. */
  readonly today: string;
}

/**
 * Resolving an instant to a day in a named zone is a general date utility, so
 * `date-utils` owns it. Re-exported here because this module's callers reach
 * for it as part of the future-journal rules, and because `date-utils` cannot
 * import back the other way.
 *
 * `todayIn` is not used here; it is re-exported for the same callers.
 */
export { localDateIn, todayIn };

/**
 * `date` moved forward by whole days, staying an ISO calendar date.
 *
 * Computed at midday UTC so a daylight-saving shift cannot move the result
 * onto the neighbouring day.
 */
export function addDaysToIsoDate(date: string, days: number): string {
  const moved = new Date(`${date}T12:00:00Z`);
  moved.setUTCDate(moved.getUTCDate() + days);
  return moved.toISOString().slice(0, 10);
}

/**
 * Whether this journal is a cancelled event.
 *
 * `invited` and `tentative` are not cancellations — the same reading the
 * backend's `find_cancelled_journal_ids` takes — and a journal with no event
 * type data is simply not an event.
 */
function isCancelledEvent(journal: JournalResource): boolean {
  const calendarInfo = journal.attributes.type_data?.[JournalType.EVENT] as
    CalendarInfoData | undefined;
  return calendarInfo?.event_state === EventState.CANCELLED;
}

/**
 * The listing, reduced to the journals a task may be made due in, nearest
 * first.
 *
 * Cancelled journals are kept: whether to offer one is the picker's decision
 * to present, not this function's to hide.
 */
export function futureJournalOptions(
  journals: readonly JournalResource[],
  { timezone, today }: FutureJournalContext
): FutureJournalOption[] {
  return journals
    .map(journal => ({
      id: journal.id,
      title: journal.attributes.title,
      date: localDateIn(timezone, journal.attributes.event_date_range.start),
      startsAt: journal.attributes.event_date_range.start,
      cancelled: isCancelledEvent(journal),
    }))
    .filter(option => option.date > today)
    .sort(
      (a, b) => new Date(a.startsAt).getTime() - new Date(b.startsAt).getTime()
    );
}

/**
 * A journal's date as every other surface writes one.
 *
 * Re-exported rather than re-implemented: the format string belongs to
 * `date-utils`, and taking the already-resolved `YYYY-MM-DD` rather than an
 * instant is what keeps the picker from disagreeing with the rule that judged
 * the option eligible.
 */
export { formatIsoDate as formatFutureJournalDate };
