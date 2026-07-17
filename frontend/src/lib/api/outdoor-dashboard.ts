/**
 * Outdoor dashboard API client using TanStack Query.
 *
 * The dashboard is a singleton read-only projection over the user's outdoor
 * activity journals (see the Outdoor Logbook Improvements spec §4): upcoming
 * activities, checked-out gear, recent activity totals, and the abseil
 * templates done. All widgets share one query so concurrent mounts dedupe
 * into a single fetch.
 */

import { useQuery } from '@tanstack/react-query';
import { EventDateRange, JournalType } from '@/types/journals';
import { JsonApiErrorResponse } from '@/types/api';
import { API_ENDPOINTS, ERROR_MESSAGES } from '@/lib/constants';

export interface UpcomingOutdoorActivityEntry {
  journal_id: number;
  title: string;
  event_date_range: EventDateRange;
  // Raw subtype presence flags (dependency-added rows included), a subset of
  // the JournalType enum values; empty for OUTDOOR_PLANNING entries.
  subtypes: JournalType[];
  is_planning: boolean;
}

export interface CheckedOutGearItem {
  gear_item_id: string;
  name: string;
  checked_out_since: string;
  journal_id: number;
}

// Counts keyed by effective (dependency-reduced) journal type.
export interface OutdoorActivityTotals {
  last_30_days: Partial<Record<JournalType, number>>;
  last_365_days: Partial<Record<JournalType, number>>;
}

export interface TemplateDone {
  template_id: string;
  name: string;
  done_count: number;
}

export interface OutdoorDashboardAttributes {
  upcoming_activities: UpcomingOutdoorActivityEntry[];
  checked_out_gear: CheckedOutGearItem[];
  activity_totals: OutdoorActivityTotals;
  templates_done: Record<string, TemplateDone[]>;
}

export interface OutdoorDashboardResponse {
  data: {
    type: string;
    id: string;
    attributes: OutdoorDashboardAttributes;
  };
}

// Query Keys
export const outdoorDashboardKeys = {
  all: ['outdoor-dashboard'] as const,
};

// API Functions
async function fetchOutdoorDashboard(): Promise<OutdoorDashboardResponse> {
  const response = await fetch(API_ENDPOINTS.JOURNALS.OUTDOOR_DASHBOARD, {
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
 * The user's outdoor dashboard: upcoming activities (next 30 days, soonest
 * first, capped at 10 server-side), checked-out gear, activity totals over
 * rolling 30/365-day windows, and templates done — all outdoor-only,
 * window-anchored on "today" in the user's timezone server-side.
 */
export function useOutdoorDashboard() {
  return useQuery({
    queryKey: outdoorDashboardKeys.all,
    queryFn: fetchOutdoorDashboard,
  });
}
