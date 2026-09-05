/**
 * User settings API client + React Query hooks.
 *
 * Persists the user's default timezone on the backend so it can be used by
 * server-side AI prompt generation. A localStorage cache is kept in sync so
 * the synchronous {@link getDefaultTimezone} helper (used when creating new
 * events) reflects the latest value without an async fetch.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import type { JsonApiErrorResponse } from '@/types/api';
import type { UserSettingsResponse } from '@/types/settings';
import { invalidateAfterMutation } from './invalidate-after-mutation';
// `journalKeys` comes from `./journal-keys` rather than `./journals`, which
// imports *this* module — see that file's header for the cycle it removes.
import { journalKeys } from './journal-keys';
import { taskKeys } from './tasks';

const USER_SETTINGS_ENDPOINT = '/api/user-settings';

/** localStorage key shared with the timezone settings UI as a cache. */
export const TIMEZONE_STORAGE_KEY = 'pms-default-timezone';

export const userSettingsKeys = {
  all: ['user-settings'] as const,
  detail: () => [...userSettingsKeys.all, 'detail'] as const,
};

/** The zone the browser reports. `'UTC'` during SSR, where there is none. */
export function getBrowserTimezone(): string {
  if (typeof window === 'undefined') {
    return 'UTC';
  }
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/**
 * The user's default timezone from the localStorage cache, falling back to the
 * browser's. Synchronous, so a caller can use it without awaiting the settings
 * read — and so it can be reached from `lib/` without importing a component.
 *
 * It lives here rather than beside the settings UI that writes it because the
 * cache key does, and because `lib/api/` must not depend on `components/`.
 *
 * A caller that *can* see the settings read should prefer
 * {@link useUserTimezone}: this answer is a guess, and a guess is only the
 * right thing while the real answer is still in flight.
 */
export function getDefaultTimezone(): string {
  if (typeof window === 'undefined') {
    return 'UTC';
  }
  const stored = localStorage.getItem(TIMEZONE_STORAGE_KEY);
  return stored || getBrowserTimezone();
}

/** Write the timezone to the localStorage cache (no-op during SSR). */
export function cacheTimezone(timezone: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TIMEZONE_STORAGE_KEY, timezone);
}

/**
 * Drop the cached timezone. Called on logout: the cache is keyed by browser,
 * not by account, so left in place it would answer for whoever signs in next —
 * indefinitely, for a user who has configured no zone of their own.
 */
export function clearCachedTimezone(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TIMEZONE_STORAGE_KEY);
}

export async function fetchUserSettings(): Promise<UserSettingsResponse> {
  const response = await fetch(USER_SETTINGS_ENDPOINT, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || 'Failed to load user settings'
    );
  }

  return response.json();
}

export async function updateTimezone(
  timezone: string
): Promise<UserSettingsResponse> {
  const response = await fetch(USER_SETTINGS_ENDPOINT, {
    method: 'PUT',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ timezone }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(errorData.errors?.[0]?.detail || 'Failed to save timezone');
  }

  return response.json();
}

export function useUserSettings() {
  return useQuery({
    queryKey: userSettingsKeys.detail(),
    queryFn: fetchUserSettings,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

/**
 * The zone to anchor a user-facing day boundary on.
 *
 * A journal's `event_date_range` bounds are stored as the UTC instant of
 * midnight *on some day in some zone*, and which zone that is has to be the
 * same one on the way in and on the way out or an untouched range drifts a
 * calendar day (issue #1401). The browser's zone cannot be that anchor — it
 * changes when the user travels — so the configured zone wins whenever there
 * is one.
 *
 * **The cache is a stand-in for a read that has not landed, and nothing more.**
 * Once the settings read resolves it is the answer, including when it answers
 * `null`: a user who has configured nothing gets the *browser's* zone, not
 * whatever `pms-default-timezone` happens to hold. That distinction is the
 * whole reason the API's `timezone` is nullable rather than defaulting to
 * `'UTC'`, and skipping it would undo it — the key is keyed by browser rather
 * than by account, so a stale value would otherwise anchor an unconfigured
 * user's writes in the previous account's zone for as long as they used that
 * browser. (Logout clears it too, via {@link clearCachedTimezone}, for the
 * callers that cannot see the read at all.)
 */
export function useUserTimezone(): string {
  const { data, isPending } = useUserSettings();

  if (isPending) {
    return getDefaultTimezone();
  }
  return data?.data.attributes.timezone ?? getBrowserTimezone();
}

export function useUpdateTimezone() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateTimezone,
    onSuccess: response => {
      // Typed nullable because a *read* can answer "not set"; a PUT echoes the
      // value it just saved, so this branch is the type system's, not a case.
      const saved = response.data.attributes.timezone;
      if (saved) {
        cacheTimezone(saved);
      }
      // Seeded, not merely invalidated. The invalidation below is
      // fire-and-forget, so until its refetch lands the query still holds the
      // zone the user has just replaced — and a non-null stored value outranks
      // everything else in `useUserTimezone`. Without this, a journal saved in
      // that window is anchored in the old zone despite a successful save.
      queryClient.setQueryData(userSettingsKeys.detail(), response);
      // **Changing the zone changes what the server thinks "today" is**, and
      // two answers are derived from that rather than stored: whether a task
      // has *lapsed*, and the journal list's `tasks_due_count`, which is the
      // same rule applied to a whole page. Both are already cached under the
      // app-wide five-minute `staleTime`, so without naming them here a user
      // who corrects their timezone keeps being shown verdicts reached in the
      // old one — including a badge for a commitment that has just lapsed.
      //
      // `journalKeys.lists()` is the reachable set on the journal side: only
      // the list endpoint computes the count. `taskKeys.all` is the whole task
      // side, because every task read carries `lapsed` and `lapse_reason`.
      //
      // One call rather than three: the key sets must all be cancelled before
      // any is invalidated, or the later ones stay exposed to the #1203 race.
      void invalidateAfterMutation(
        queryClient,
        { queryKey: userSettingsKeys.all },
        { queryKey: journalKeys.lists() },
        { queryKey: taskKeys.all }
      );
      toast.success('Timezone saved');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
