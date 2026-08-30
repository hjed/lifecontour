/**
 * Home dashboard API client using TanStack Query.
 *
 * The dashboard is a singleton read-only projection whose id is the user id
 * (see the Home Dashboard & Tasks spec §*The Home Dashboard*): today's AI
 * summary as the headline, over the agenda, the tasks due this week and the
 * upcoming contact dates. Every section is retrieved **together in one round
 * trip**, so the page header and all four cards share one query and concurrent
 * mounts dedupe into a single fetch — the same arrangement
 * `outdoor-dashboard.ts` uses.
 *
 * Two shapes here come straight from the endpoint's contract and are worth
 * knowing before rendering anything:
 *
 * - **A section reports its own availability.** `ready` means it has a payload,
 *   and an empty payload is a real answer (nothing scheduled, nothing due).
 *   `unavailable` means it has nothing — whether it could not be read or there
 *   is none to report, a distinction deliberately absent from the wire — and
 *   `data` is then `null`. One section failing never fails the request.
 * - **The day is in `meta.anchor`, not in a section.** It is the server's today
 *   in the user's configured timezone, and it is what a surface must label the
 *   page with; the browser's idea of today can differ.
 */

import { useQuery } from '@tanstack/react-query';
import { JsonApiErrorResponse } from '@/types/api';
import { API_ENDPOINTS, ERROR_MESSAGES } from '@/lib/constants';

/** Whether a section has a payload for you. */
export enum DashboardSectionStatus {
  READY = 'ready',
  UNAVAILABLE = 'unavailable',
}

/**
 * One section's envelope: whether it has anything, and what.
 *
 * `data` is `null` exactly when `status` is `unavailable` — the server derives
 * the pair from the payload so the two cannot drift apart.
 */
export interface DashboardSection<T> {
  status: DashboardSectionStatus;
  data: T | null;
}

/**
 * The state of today's summary. There is no third value: a day with no summary
 * makes the whole section `unavailable` rather than adding an "absent" state.
 */
export enum DashboardSummaryState {
  GENERATED = 'generated',
  GENERATING = 'generating',
}

/**
 * Today's daily summary — the same entity the journals view shows.
 *
 * `summary_text` is null while generating: null rather than stale, because an
 * invalidated summary keeps its old text in storage and this never returns it.
 * The four counters ride in both states; which of them to draw is the card's
 * decision (they are the key-stats footer, W10).
 */
export interface HomeDashboardSummary {
  state: DashboardSummaryState;
  summary_text: string | null;
  journal_count: number;
  event_count: number;
  contact_count: number;
  /** Out of ten, or null when nothing was rated — which is most days. */
  mood_average: number | null;
}

/** Today's event journals, and tomorrow's. Fields land in Phases 5 and 6. */
export type HomeDashboardAgenda = Record<string, never>;

/** Not-done tasks due in the next seven days. Fields land in Phase 13. */
export type HomeDashboardTasks = Record<string, never>;

/** Important contact dates in the same seven days. Fields land in Phase 11. */
export type HomeDashboardUpcomingDates = Record<string, never>;

export interface HomeDashboardAttributes {
  summary: DashboardSection<HomeDashboardSummary>;
  agenda: DashboardSection<HomeDashboardAgenda>;
  tasks: DashboardSection<HomeDashboardTasks>;
  upcoming_dates: DashboardSection<HomeDashboardUpcomingDates>;
}

/** The day every section was read for, and the zone that decided it. */
export interface HomeDashboardAnchor {
  /** Today in the user's configured timezone, as `YYYY-MM-DD`. */
  date: string;
  /** The IANA zone it was resolved in — UTC when unset or unrecognised. */
  timezone: string;
}

export interface HomeDashboardResponse {
  data: {
    type: string;
    id: string;
    attributes: HomeDashboardAttributes;
  };
  /**
   * Required rather than optional: the anchor is how a client knows which day
   * it is rendering, and that is true even when every section is empty.
   */
  meta: {
    anchor: HomeDashboardAnchor;
  };
}

// Query Keys
export const homeDashboardKeys = {
  all: ['home-dashboard'] as const,
};

// API Functions
async function fetchHomeDashboard(): Promise<HomeDashboardResponse> {
  const response = await fetch(API_ENDPOINTS.HOME_DASHBOARD, {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

// Hooks

/**
 * The user's home dashboard: today's summary, agenda, tasks due in the next
 * seven days and upcoming contact dates, every window anchored server-side on
 * today in the user's timezone.
 *
 * Every part of the page calls this hook rather than being handed props from
 * one caller, so a section is free to mount, unmount and render on its own —
 * and they still cost one request between them.
 */
export function useHomeDashboard() {
  return useQuery({
    queryKey: homeDashboardKeys.all,
    queryFn: fetchHomeDashboard,
  });
}
