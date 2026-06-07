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

const USER_SETTINGS_ENDPOINT = '/api/user-settings';

/** localStorage key shared with the timezone settings UI as a cache. */
export const TIMEZONE_STORAGE_KEY = 'pms-default-timezone';

export const userSettingsKeys = {
  all: ['user-settings'] as const,
  detail: () => [...userSettingsKeys.all, 'detail'] as const,
};

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
      queryClient.invalidateQueries({ queryKey: userSettingsKeys.all });
      toast.success('Timezone saved');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
