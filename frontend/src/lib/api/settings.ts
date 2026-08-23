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

const USER_SETTINGS_ENDPOINT = '/api/user-settings';

/** localStorage key shared with the timezone settings UI as a cache. */
export const TIMEZONE_STORAGE_KEY = 'pms-default-timezone';

export const userSettingsKeys = {
  all: ['user-settings'] as const,
  detail: () => [...userSettingsKeys.all, 'detail'] as const,
};

/**
 * The user's default timezone from the localStorage cache, falling back to the
 * browser's. Synchronous, so a caller can use it without awaiting the settings
 * read — and so it can be reached from `lib/` without importing a component.
 *
 * It lives here rather than beside the settings UI that writes it because the
 * cache key does, and because `lib/api/` must not depend on `components/`.
 */
export function getDefaultTimezone(): string {
  if (typeof window === 'undefined') {
    return 'UTC';
  }
  const stored = localStorage.getItem(TIMEZONE_STORAGE_KEY);
  return stored || Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Write the timezone to the localStorage cache (no-op during SSR). */
export function cacheTimezone(timezone: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TIMEZONE_STORAGE_KEY, timezone);
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

export function useUpdateTimezone() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateTimezone,
    onSuccess: response => {
      cacheTimezone(response.data.attributes.timezone);
      void invalidateAfterMutation(queryClient, {
        queryKey: userSettingsKeys.all,
      });
      toast.success('Timezone saved');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
