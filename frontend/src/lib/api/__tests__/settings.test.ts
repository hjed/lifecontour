/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';

import {
  TIMEZONE_STORAGE_KEY,
  clearCachedTimezone,
  fetchUserSettings,
  journalTimezone,
  updateTimezone,
  useUpdateTimezone,
  useUserSettings,
  useUserTimezone,
} from '../settings';
import { userSettingsKeys } from '../settings';
import { journalKeys } from '../journal-keys';
import { taskKeys } from '../tasks';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

describe('settings API', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('fetchUserSettings', () => {
    it('GETs the user settings endpoint with credentials', async () => {
      const mockResponse = {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: { timezone: 'Australia/Sydney' },
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await fetchUserSettings();

      expect(mockFetch).toHaveBeenCalledWith('/api/user-settings', {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      expect(result).toEqual(mockResponse);
    });

    it('throws the API error detail on failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          errors: [{ detail: 'boom' }],
        }),
      } as Response);

      await expect(fetchUserSettings()).rejects.toThrow('boom');
    });
  });

  describe('updateTimezone', () => {
    it('PUTs the timezone in the request body', async () => {
      const mockResponse = {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: { timezone: 'America/New_York' },
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await updateTimezone('America/New_York');

      expect(mockFetch).toHaveBeenCalledWith('/api/user-settings', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: 'America/New_York' }),
      });
      expect(result).toEqual(mockResponse);
    });
  });

  function wrapper(client: QueryClient) {
    return function Wrapper({ children }: { children: ReactNode }) {
      return React.createElement(QueryClientProvider, { client }, children);
    };
  }

  /**
   * The cache is a stand-in for a read that has not landed yet — nothing more.
   * Once the server has said the user has no configured zone, preferring a
   * cached value defeats the nullable field it answers with, and because the
   * key outlives a session it can hand one account's zone to the next person
   * to use the browser.
   */
  describe('useUserTimezone', () => {
    const BROWSER_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

    function settingsRespondWith(timezone: string | null) {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          data: {
            id: 'user-1',
            type: 'user_settings',
            attributes: { timezone },
          },
        }),
      } as Response);
    }

    function renderTimezone() {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      return renderHook(
        () => ({
          timezone: useUserTimezone(),
          isLoaded: useUserSettings().isSuccess,
        }),
        { wrapper: wrapper(queryClient) }
      );
    }

    beforeEach(() => {
      localStorage.clear();
    });

    it('stands in with the cached zone while the read is in flight', () => {
      localStorage.setItem(TIMEZONE_STORAGE_KEY, 'America/New_York');
      settingsRespondWith('America/New_York');

      const { result } = renderTimezone();

      // Asserted on the first render, before the query resolves.
      expect(result.current.isLoaded).toBe(false);
      expect(result.current.timezone).toBe('America/New_York');
    });

    it('uses the configured zone once the read lands', async () => {
      settingsRespondWith('Europe/Berlin');

      const { result } = renderTimezone();

      await waitFor(() => expect(result.current.isLoaded).toBe(true));
      expect(result.current.timezone).toBe('Europe/Berlin');
    });

    it('falls back to the browser, not the cache, once the server says null', async () => {
      // A previous account's zone, left behind in a cache that survives logout.
      localStorage.setItem(TIMEZONE_STORAGE_KEY, 'America/New_York');
      settingsRespondWith(null);

      const { result } = renderTimezone();

      await waitFor(() => expect(result.current.isLoaded).toBe(true));
      expect(result.current.timezone).toBe(BROWSER_ZONE);
    });

    it('answers UTC for a configured UTC, which is not the same as unset', async () => {
      settingsRespondWith('UTC');

      const { result } = renderTimezone();

      await waitFor(() => expect(result.current.isLoaded).toBe(true));
      expect(result.current.timezone).toBe('UTC');
    });
  });

  /**
   * `journal_calendar_info.timezone` is the zone the backend and the Google
   * worker *read* a journal's `event_date_range` bounds through, so bounds
   * anchored anywhere else are read as the wrong calendar day. That makes the
   * event's own zone the anchor whenever it records one — and makes this
   * precedence the one rule the read path and the write path must never
   * disagree about, which is why it has a name rather than being spelled out
   * at each site.
   */
  describe('journalTimezone', () => {
    it("uses the event's own zone when the journal records one", () => {
      expect(journalTimezone('America/New_York', 'Australia/Sydney')).toBe(
        'America/New_York'
      );
    });

    it.each([
      ['no zone recorded', undefined],
      ['an explicit null', null],
      ['an empty string, which records nothing', ''],
    ])('falls back to the user for %s', (_, eventTimezone) => {
      expect(journalTimezone(eventTimezone, 'Australia/Sydney')).toBe(
        'Australia/Sydney'
      );
    });
  });

  describe('clearCachedTimezone', () => {
    it('removes the cached zone so it cannot outlive the session', () => {
      localStorage.setItem(TIMEZONE_STORAGE_KEY, 'America/New_York');

      clearCachedTimezone();

      expect(localStorage.getItem(TIMEZONE_STORAGE_KEY)).toBeNull();
    });
  });

  describe('useUpdateTimezone', () => {
    /**
     * Changing the zone changes what "today" is, and two answers are *derived*
     * from that rather than stored: whether a task has lapsed, and the journal
     * list's `tasks_due_count`, which is the same rule over a whole page. Both
     * sit behind the app-wide five-minute `staleTime`, so a mutation that named
     * only its own namespace would leave the user looking at verdicts reached
     * in the zone they have just corrected.
     */
    it('invalidates the timezone-derived reads, not only its own', async () => {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: 'user-1',
            type: 'user_settings',
            attributes: { timezone: 'Australia/Sydney' },
          },
        }),
      } as Response);

      const { result } = renderHook(() => useUpdateTimezone(), {
        wrapper: wrapper(queryClient),
      });

      await result.current.mutateAsync('Australia/Sydney');

      await waitFor(() => {
        const keys = invalidateSpy.mock.calls.map(
          ([filters]) => filters?.queryKey
        );
        expect(keys).toContainEqual(journalKeys.lists());
        expect(keys).toContainEqual(taskKeys.all);
      });
    });

    /**
     * The invalidation is fire-and-forget, so between a successful PUT and the
     * refetch landing the query still holds the *previous* zone — and a
     * non-null previous zone outranks everything else in `useUserTimezone`. A
     * journal written in that window would be anchored in the zone the user
     * has just replaced, which is why the response is seeded straight into the
     * query rather than only invalidated.
     */
    it('makes the saved zone authoritative before any refetch lands', async () => {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      queryClient.setQueryData(userSettingsKeys.detail(), {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: { timezone: 'Australia/Sydney' },
        },
      });
      // The PUT answers; the refetch the invalidation triggers never lands, so
      // the only thing that can move the hook off the old zone is the seed.
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            data: {
              id: 'user-1',
              type: 'user_settings',
              attributes: { timezone: 'America/New_York' },
            },
          }),
        } as Response)
        .mockReturnValue(new Promise<Response>(() => {}));

      const { result } = renderHook(
        () => ({
          save: useUpdateTimezone(),
          timezone: useUserTimezone(),
        }),
        { wrapper: wrapper(queryClient) }
      );

      expect(result.current.timezone).toBe('Australia/Sydney');

      await result.current.save.mutateAsync('America/New_York');

      await waitFor(() =>
        expect(result.current.timezone).toBe('America/New_York')
      );
    });
  });
});
