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

import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { JsonApiErrorResponse } from '@/types/api';
import { ImportantDateTypeEnum } from '@/types/contacts';
import { API_ENDPOINTS, ERROR_MESSAGES } from '@/lib/constants';
import { msUntilNextAnchorDay } from '@/lib/dashboard-anchor';

/**
 * The longest delay a `setTimeout` can hold; past it a browser fires
 * immediately. A timer concern, so it lives with the timer rather than with the
 * arithmetic that says when the anchor day ends.
 */
const MAX_TIMEOUT_MS = 2_147_483_647;

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

/** One of an entry's tags, with the colour its badge is drawn in (W15). */
export interface HomeDashboardAgendaTag {
  id: string;
  name: string;
  /** Hex, or null. Decoration only — the name is what carries the meaning. */
  color: string | null;
}

/** Somebody at the event, for the entry's avatar stack (W16). */
export interface HomeDashboardAgendaParticipant {
  contact_id: number;
  name: string;
}

/**
 * One event journal on the agenda.
 *
 * Deliberately data rather than finished strings, so the card owns how it is
 * rendered accessibly: all-day and cancelled are booleans, tags carry a name
 * beside their colour, and participants carry names for the avatar stack.
 *
 * **Two time representations, answering different questions.** `starts_at` and
 * `ends_at` are the journal's stored instants — what the list is ordered by, and
 * the only way to tell that an entry began before today. `start_time` and
 * `end_time` are clock values in the *event's own* zone, which is why
 * `timezone` travels with them: render them against that, not against
 * `meta.anchor.timezone`. Both clock values are null for an all-day entry.
 */
export interface HomeDashboardAgendaEntry {
  journal_id: number;
  title: string;
  is_all_day: boolean;
  starts_at: string;
  ends_at: string;
  start_time: string | null;
  end_time: string | null;
  /** IANA zone the clock values are in; null means UTC. */
  timezone: string | null;
  location: string | null;
  /** The calendar's colour, which W17 keys the row's accent bar to. */
  calendar_color: string | null;
  /**
   * Cancelled events arrive flagged rather than filtered, so the card can mark
   * them (W18). A surface must never present one as still happening.
   */
  is_cancelled: boolean;
  tags: HomeDashboardAgendaTag[];
  participants: HomeDashboardAgendaParticipant[];
}

/**
 * One day's event journals — the shape tomorrow arrives in (W19, W20).
 *
 * A *day* rather than a bare list: `date` is the local day the server windowed
 * on, as `YYYY-MM-DD` in `meta.anchor.timezone`, and it is what the disclosure
 * labels itself with — never a date the browser worked out in its own zone.
 * The collapsed count is `entries.length`; the list is not capped, so no
 * separate count is sent.
 */
export interface HomeDashboardAgendaDay {
  date: string;
  /** Same form and same order as today's entries; may be empty. */
  entries: HomeDashboardAgendaEntry[];
}

/**
 * Today's event journals, in the order the card draws them: all-day entries
 * first, then timed ones ascending by start — with tomorrow's beneath them.
 *
 * An **empty list is a real answer** — nothing is scheduled today — and is not
 * the same as the section being unavailable, where `data` is null instead.
 *
 * `tomorrow` rides in the same payload so the page stays one round trip, and
 * it is always present on a ready agenda, so "nothing tomorrow" is an empty
 * `entries` rather than a missing day.
 */
export interface HomeDashboardAgenda {
  entries: HomeDashboardAgendaEntry[];
  tomorrow: HomeDashboardAgendaDay;
}

/** One person a task references, as a row shows them (W27). */
export interface HomeDashboardTaskContact {
  contact_id: number;
  /**
   * Their given and family names, or `Contact {id}` when the record has
   * neither. **Not** the nickname rule `HomeDashboardUpcomingDate` follows: the
   * tasks read builds this name in SQL from two columns and never sees
   * `nick_name`, so one contact can read differently in the two cards. A known
   * divergence in the tasks read, not this section's choice.
   */
  name: string;
  photo_url: string | null;
}

/** The journal a task is due in — the row's link and its date (W26). */
export interface HomeDashboardTaskJournal {
  id: number;
  title: string;
  /** `YYYY-MM-DD` in `meta.anchor.timezone`, already resolved server-side. */
  date: string;
}

/**
 * One task due this week, as a row renders it (W22–W27).
 *
 * **Less than the task resource `GET /api/tasks/{id}` returns, deliberately.**
 * Every task here is not done, has not lapsed and is due in a journal that was
 * not cancelled — those are the section's entry conditions — so there is no
 * `status`, no `lapsed` and no cancelled marker to branch on, and no creating
 * or intermediate journals, which no row draws.
 *
 * **`days_away` is authoritative and must not be re-derived**, the same trap
 * `HomeDashboardUpcomingDate` carries: it counts from the window's first day,
 * which is `meta.anchor.date` in the user's configured zone, so the chip and
 * the page header agree. Subtracting `due_journal.date` from the browser's
 * today can land a day out near midnight in any other zone.
 */
export interface HomeDashboardTask {
  /** The task itself — what the inline done action patches. */
  task_id: number;
  text: string;
  due_journal: HomeDashboardTaskJournal;
  /** Days from the window's first day; `0` is today. See the note above. */
  days_away: number;
  /** In link order. Empty is ordinary — most tasks name nobody. */
  contacts: HomeDashboardTaskContact[];
}

/** The span the tasks were read for, in the acting user's timezone. */
export interface HomeDashboardTasksWindow {
  /** Today in the user's zone — the window includes it. */
  start_date: string;
  /** The last day, also included. */
  end_date: string;
  /** How far ahead the section looked, echoed so no arithmetic is needed. */
  days_ahead: number;
}

/**
 * Not-done tasks due between today and seven days ahead, soonest first.
 *
 * **The whole window travels and `total` equals `tasks.length`**: the server
 * caps nothing, so the card's show-more reveals the remainder from data it
 * already holds rather than making a second request. `total` is named anyway
 * because it is the number the show-more displays.
 *
 * Done, cancelled and **lapsed** tasks are absent, and they stay on their own
 * journals — there is no overdue list, counter or badge on this page. An
 * **empty list is a real answer** and reads as a good outcome, not an error.
 */
export interface HomeDashboardTasks {
  window: HomeDashboardTasksWindow;
  total: number;
  tasks: HomeDashboardTask[];
}

/**
 * One important contact date coming up, as a row renders it (W31).
 *
 * Two fields carry traps worth knowing before rendering either:
 *
 * - **`days_away` is authoritative and must not be re-derived.** It counts from
 *   the window's first day, which the server resolved in the user's configured
 *   zone. Subtracting `occurs_on` from the browser's today can land a day out
 *   near midnight in any zone away from that one, so the chip renders this
 *   number rather than working one out.
 * - **`years` is null where there is no answer**, and **`0` is a real count**.
 *   A row with no stored year, or one recorded after the occurrence, has no
 *   age to show and degrades to the bare type; a first birthday genuinely
 *   turns 0. Test `years !== null`, never truthiness.
 */
export interface HomeDashboardUpcomingDate {
  contact_id: number;
  /** Their nickname where they have one, by the app's usual display rule. */
  contact_name: string;
  photo_url: string | null;
  date_type: ImportantDateTypeEnum;
  /** Present only for a `custom` date. Show this, never the word "custom". */
  custom_date_type_name: string | null;
  /** The day it falls on this time round, `YYYY-MM-DD` in the anchor's zone. */
  occurs_on: string;
  /** Days from the window's first day; `0` is today. See the note above. */
  days_away: number;
  /** The age or count this occurrence makes, or null. See the note above. */
  years: number | null;
  /**
   * Whether `occurs_on` stands in for a 29 February in a year without one.
   * Sent so a surface can say so rather than appearing to show a wrong day.
   */
  observed_for_leap_day: boolean;
}

/** The span the dates were read for, in the acting user's timezone. */
export interface HomeDashboardUpcomingDatesWindow {
  /** Today in the user's zone — the window includes it. */
  start_date: string;
  /** The last day, also included. */
  end_date: string;
  /** How far ahead the section looked, echoed so no arithmetic is needed. */
  days_ahead: number;
}

/**
 * Important contact dates in the same seven days the tasks cover.
 *
 * **The whole window travels and `total` equals `dates.length`**: the server
 * caps nothing, so the card's show-more reveals the remainder from data it
 * already holds rather than making a second request. `total` is named anyway
 * because it is the number the show-more displays.
 *
 * The order is date ascending and, within a day, by how much the contact
 * matters to you — inferred from signals the payload deliberately omits, so a
 * surface **cannot** reproduce this order and must not re-sort. An **empty
 * list is a real answer** and is not the section being unavailable.
 */
export interface HomeDashboardUpcomingDates {
  window: HomeDashboardUpcomingDatesWindow;
  total: number;
  dates: HomeDashboardUpcomingDate[];
}

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
export function useHomeDashboard(
  options: { readonly refetchOnMount?: 'always' } = {}
) {
  return useQuery({
    queryKey: homeDashboardKeys.all,
    queryFn: fetchHomeDashboard,
    ...(options.refetchOnMount
      ? { refetchOnMount: options.refetchOnMount }
      : {}),
  });
}

/**
 * Whether this visit has a settled read of the dashboard: one this mount made,
 * that succeeded, with nothing in flight.
 *
 * The one answer the summary card's read on load and its hold share (Augment
 * review on PR #1470). Data alone says nothing about *this* visit: on
 * client-side navigation back, the previous visit's cached payload renders while
 * the mount refetch runs, React Query keeps that payload when the refetch
 * fails, and inside the stale time it renders a fresh cached payload with no
 * request at all — so a read counts only once this mount has made it. The page
 * refetches on mount (`useHomeDashboard({ refetchOnMount: 'always' })`), which
 * is what gives every visit that read.
 */
export function isSettledDashboardRead(read: {
  readonly isSuccess: boolean;
  readonly isFetching: boolean;
  readonly isFetchedAfterMount: boolean;
}): boolean {
  return read.isSuccess && !read.isFetching && read.isFetchedAfterMount;
}

/**
 * Refresh the dashboard when its anchor day ends.
 *
 * The whole page is read for one day and every window hangs off it, so a
 * dashboard left open *and focused* across local midnight keeps yesterday's
 * anchor — and, since Phase 3, yesterday's date in the **W2** header. That is
 * the same "a wrong date is worse than none" failure the header refuses when it
 * declines to guess a date, arriving by a different route; Phase 3 recorded it
 * as owned by Phase 16 and this is it.
 *
 * Called **once**, by the page. Every card reads the query itself, and one
 * timer per card would be four timers invalidating one query key.
 *
 * **The effect is keyed on the anchor, and that is what makes it terminate.**
 * An anchor already in the past is due immediately, which is right for a
 * payload cached across midnight; if the refetch comes back with the *same*
 * anchor — a browser clock that disagrees with the server about the day — the
 * dependencies have not moved, the effect does not run again, and there is no
 * loop. A refetch that does move the day reschedules for the next boundary.
 *
 * **That same property is why the timer sleeps in instalments.** A boundary
 * further off than a `setTimeout` can hold — a browser clock weeks behind, or
 * an anchor the server should never send — cannot be waited for in one go, and
 * simply capping the delay would *invalidate early*: the refetch would return
 * the same anchor, the effect would not run again, and the page would be left
 * with no timer at all. So a capped wait re-arms rather than firing, and only a
 * timer that actually reached the boundary invalidates.
 */
export function useAnchorDayRefresh(anchor: HomeDashboardAnchor | undefined) {
  const queryClient = useQueryClient();
  const date = anchor?.date;
  const timezone = anchor?.timezone;

  useEffect(() => {
    if (date === undefined || timezone === undefined) {
      return;
    }

    let timer: ReturnType<typeof setTimeout> | undefined;

    const arm = () => {
      const remaining = msUntilNextAnchorDay({ date, timezone });
      if (remaining === null) {
        // An anchor that cannot be read schedules nothing: the arithmetic
        // would be `NaN`, and `setTimeout(NaN)` fires immediately, not never.
        return;
      }

      // Re-measured on each arming rather than counted down, so a machine that
      // slept through part of the wait still stops at the right instant.
      const wait = Math.min(Math.max(remaining, 0), MAX_TIMEOUT_MS);
      timer = setTimeout(() => {
        if (wait < remaining) {
          // Only part of the way there. Sleeping again rather than
          // invalidating is the whole point: an early invalidation would
          // return the same anchor, and the effect — keyed on that anchor —
          // would not run again to schedule anything else.
          arm();
          return;
        }
        void queryClient.invalidateQueries({ queryKey: homeDashboardKeys.all });
      }, wait);
    };

    arm();

    return () => clearTimeout(timer);
  }, [date, timezone, queryClient]);
}
