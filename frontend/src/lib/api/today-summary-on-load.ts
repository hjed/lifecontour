/**
 * Obtaining today's summary when the dashboard loads (ITER18-005 Phase 8).
 *
 * The dashboard's own read never generates: `GET /api/home-dashboard` reads the
 * stored row, because a page load must not hold a multi-second AI call open.
 * So after an invalidation, or on a new day, the row it reads says
 * *generating* — or there is no row at all — with nothing generating it, and
 * the specification says the summary "refreshes on the next load". This hook
 * is that refresh. Once per mount of the card and anchor day, when the first
 * settled read of today has no prose, it reads today's summary through
 * `GET /api/journals/daily-summary/{date}`, which serves a fresh summary from
 * cache and regenerates a missing, invalidated or stale one
 * (`DailySummaryService.get_or_generate`), and then reads the dashboard back so
 * the card can draw what came of it.
 *
 * It **reads**; it never forces. `POST …/regenerate` stays the reader's own
 * action, and lazy invalidation still turns four ticked tasks into one
 * generation, on the next load. The read does write a derived row, which is the
 * one place this page departs from the specification's "nothing on it mutates
 * data except the inline task actions" — a user decision taken in ITER18-005
 * Phase 8, because that same specification requires the refresh.
 *
 * Five properties are load-bearing, and each is what a naive version gets wrong:
 *
 * - **Decided once per anchor day, on the first settled read.** "Settled"
 *   means a read that succeeded with no fetch in flight
 *   (`isSettledDashboardRead`), so neither a stale cached payload shown on
 *   client-side navigation nor one left behind by a failed refetch can decide
 *   for this visit. Later reads of
 *   the same day never decide again: a task tick's refetch reports today
 *   generating, and re-reading then would regenerate underneath the reader.
 * - **A query that can never refetch itself.** No retry, no refetch on focus,
 *   mount or reconnect, and a key outside `homeDashboardKeys.all` and
 *   `journalKeys.all`, so neither namespace's invalidations reach it. The app's
 *   defaults — retry three times, refetch on focus — would each regenerate
 *   the summary while the user is on the page.
 * - **The read-back yields to a task write in flight, and only to one.** A tick
 *   refetches the dashboard when it settles; a read-back landing first would
 *   answer from a server that has not processed the tick and put back a row it
 *   removed optimistically. So the read-back waits for `isTaskWrite` mutations
 *   — the predicate the tick's own refresh counts with — and runs once they
 *   have settled. Any other mutation leaves it alone.
 * - **Settled means the read-back itself finished**, however it finished. The
 *   promise resolves on success, failure and cancellation alike, so a dashboard
 *   that fails to answer cannot leave Regenerate busy for the rest of the visit.
 *   An answer with no row settles at once: nothing changed, so there is nothing
 *   to read back.
 * - **`isObtaining` is derived, not stored**, so it is already true on the
 *   first render that holds the dashboard's data — the card marks Regenerate
 *   busy from its first paint rather than one effect later.
 */

import { useEffect, useId, useState } from 'react';
import { useIsMutating, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAnchorStillToday } from '@/lib/dashboard-anchor';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
  homeDashboardKeys,
  isSettledDashboardRead,
  useHomeDashboard,
} from './home-dashboard';
import { invalidateAfterMutation } from './invalidate-after-mutation';
import { fetchDailySummary } from './journals';
import { isTaskWrite } from './tasks';

/**
 * Keyed per mount as well as per day. `gcTime: 0` evicts a query on a timer
 * rather than at once, so a card that remounts before that timer runs would
 * otherwise be answered from the previous visit's read, which never goes stale
 * and never refetches on mount — and a load that must read today's summary
 * would read nothing (Augment review on PR #1470).
 */
const todaySummaryOnLoadKeys = {
  day: (mountId: string, date: string) =>
    ['today-summary-on-load', mountId, date] as const,
};

/** What the first settled read of an anchor day decided. */
interface LoadDecision {
  readonly date: string;
  readonly obtain: boolean;
}

export interface TodaySummaryOnLoad {
  /** Today's summary is being read, or the dashboard read back after it. */
  readonly isObtaining: boolean;
}

export function useObtainTodaySummaryOnLoad(): TodaySummaryOnLoad {
  const queryClient = useQueryClient();
  const mountId = useId();
  const { data, isFetching, isSuccess, isFetchedAfterMount } =
    useHomeDashboard();
  const [decision, setDecision] = useState<LoadDecision | null>(null);
  const [readBackFor, setReadBackFor] = useState<string | null>(null);
  const taskWritesInFlight = useIsMutating({ predicate: isTaskWrite });

  const anchor = data?.meta.anchor;
  const liveDate =
    anchor && isAnchorStillToday(anchor) ? anchor.date : undefined;
  const section = data?.data.attributes.summary;
  const hasProse =
    section?.status === DashboardSectionStatus.READY &&
    section.data?.state === DashboardSummaryState.GENERATED &&
    Boolean(section.data.summary_text);

  // Decided while rendering, the way React stores information from a previous
  // render: the decision is part of *this* render's output, so there is no
  // frame in which the card shows an idle Regenerate over a read about to start.
  const undecided =
    data !== undefined &&
    liveDate !== undefined &&
    isSettledDashboardRead({ isSuccess, isFetching, isFetchedAfterMount }) &&
    decision?.date !== liveDate;
  if (undecided) {
    setDecision({ date: liveDate, obtain: !hasProse });
  }

  const obtainFor =
    decision?.obtain && decision.date === liveDate ? decision.date : undefined;

  const obtained = useQuery({
    queryKey: todaySummaryOnLoadKeys.day(mountId, obtainFor ?? ''),
    queryFn: ({ queryKey: [, , date] }) => fetchDailySummary(date),
    enabled: obtainFor !== undefined,
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const answeredWithRow = obtained.isSuccess && obtained.data.data !== null;
  const readBackDue =
    obtainFor !== undefined && answeredWithRow && readBackFor !== obtainFor;

  useEffect(() => {
    if (!readBackDue || taskWritesInFlight > 0 || obtainFor === undefined) {
      return;
    }
    // A write that starts while this read-back is out re-runs the effect; the
    // superseded read-back is then not counted, and a fresh one follows the
    // write instead.
    let current = true;
    const settle = () => {
      if (current) {
        setReadBackFor(obtainFor);
      }
    };
    invalidateAfterMutation(queryClient, {
      queryKey: homeDashboardKeys.all,
    }).then(settle, settle);
    return () => {
      current = false;
    };
  }, [queryClient, readBackDue, taskWritesInFlight, obtainFor]);

  const settled =
    obtained.isError ||
    (obtained.isSuccess &&
      (obtained.data.data === null || readBackFor === obtainFor));

  const decidingToObtain = undecided && !hasProse;
  return {
    isObtaining: decidingToObtain || (obtainFor !== undefined && !settled),
  };
}
