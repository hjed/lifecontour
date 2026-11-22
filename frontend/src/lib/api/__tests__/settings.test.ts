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
  updateUserSettings,
  useUpdateAppearance,
  useUpdateLocalisation,
  useUserSettings,
  useUserTimezone,
} from '../settings';
import { userSettingsKeys } from '../settings';
import { journalKeys } from '../journal-keys';
import { taskKeys } from '../tasks';
import { PALETTE_ATTRIBUTE } from '@/lib/theme/palettes';
import type { UserSettingsResponse } from '@/types/settings';

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

  describe('updateUserSettings', () => {
    it('PATCHes an explicit null to clear the default country', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: 'user-1',
            type: 'user_settings',
            attributes: { timezone: null, default_country: null },
          },
        }),
      } as Response);

      await updateUserSettings({ default_country: null });

      expect(mockFetch).toHaveBeenCalledWith('/api/user-settings', {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ default_country: null }),
      });
    });

    it('PATCHes an explicit null to return to the default palette', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: 'user-1',
            type: 'user_settings',
            attributes: {
              timezone: null,
              default_country: null,
              theme_palette: null,
            },
          },
        }),
      } as Response);

      await updateUserSettings({ theme_palette: null });

      expect(mockFetch).toHaveBeenCalledWith('/api/user-settings', {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme_palette: null }),
      });
    });

    it('throws the API error detail on failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{ detail: 'bad country' }] }),
      } as Response);

      await expect(
        updateUserSettings({ default_country: 'XX' })
      ).rejects.toThrow('bad country');
    });
  });

  describe('useUpdateLocalisation', () => {
    it('PATCHes the timezone and country together and seeds the query', async () => {
      localStorage.clear();
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const saved = {
        data: {
          id: 'user-1',
          type: 'user_settings' as const,
          attributes: { timezone: 'Pacific/Auckland', default_country: 'NZ' },
        },
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => saved,
      } as Response);

      const { result } = renderHook(() => useUpdateLocalisation(), {
        wrapper: wrapper(queryClient),
      });

      await result.current.mutateAsync({
        timezone: 'Pacific/Auckland',
        default_country: 'NZ',
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/user-settings',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({
            timezone: 'Pacific/Auckland',
            default_country: 'NZ',
          }),
        })
      );
      expect(queryClient.getQueryData(userSettingsKeys.detail())).toEqual(
        saved
      );
      expect(localStorage.getItem(TIMEZONE_STORAGE_KEY)).toBe(
        'Pacific/Auckland'
      );
    });

    it('keeps the palette the appearance card saved meanwhile', async () => {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      // The palette was saved after this PATCH's response was built.
      queryClient.setQueryData(userSettingsKeys.detail(), {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: {
            timezone: null,
            default_country: null,
            theme_palette: 'emerald',
          },
        },
      });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: 'user-1',
            type: 'user_settings',
            attributes: {
              timezone: 'Pacific/Auckland',
              default_country: 'NZ',
              theme_palette: null,
            },
          },
        }),
      } as Response);
      // The follow-up refetch has not landed when the cache is read.
      mockFetch.mockReturnValue(new Promise(() => {}));
      const { result } = renderHook(() => useUpdateLocalisation(), {
        wrapper: wrapper(queryClient),
      });

      await result.current.mutateAsync({ timezone: 'Pacific/Auckland' });

      const attributes = queryClient.getQueryData<UserSettingsResponse>(
        userSettingsKeys.detail()
      )?.data.attributes;
      expect(attributes?.timezone).toBe('Pacific/Auckland');
      expect(attributes?.theme_palette).toBe('emerald');
    });

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

      const { result } = renderHook(() => useUpdateLocalisation(), {
        wrapper: wrapper(queryClient),
      });

      await result.current.mutateAsync({
        timezone: 'Australia/Sydney',
        default_country: null,
      });

      await waitFor(() => {
        const keys = invalidateSpy.mock.calls.map(
          ([filters]) => filters?.queryKey
        );
        expect(keys).toContainEqual(journalKeys.lists());
        expect(keys).toContainEqual(taskKeys.all);
      });
    });

    /**
     * The invalidation is fire-and-forget, so between a successful PATCH and the
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
          save: useUpdateLocalisation(),
          timezone: useUserTimezone(),
        }),
        { wrapper: wrapper(queryClient) }
      );

      expect(result.current.timezone).toBe('Australia/Sydney');

      await result.current.save.mutateAsync({
        timezone: 'America/New_York',
        default_country: null,
      });

      await waitFor(() =>
        expect(result.current.timezone).toBe('America/New_York')
      );
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
  describe('useUserSettings', () => {
    it('does not read the settings while disabled (e.g. signed out)', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });

      const { result } = renderHook(() => useUserSettings({ enabled: false }), {
        wrapper: wrapper(queryClient),
      });

      // A settings read on the login page is a guaranteed 401.
      await waitFor(() => expect(result.current.fetchStatus).toBe('idle'));
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('useUpdateAppearance', () => {
    const root = document.documentElement;

    function settingsResponse(themePalette: string | null) {
      return {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: {
            timezone: 'Australia/Sydney',
            default_country: 'AU',
            theme_palette: themePalette,
          },
        },
      };
    }

    function renderAppearance() {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      queryClient.setQueryData(
        userSettingsKeys.detail(),
        settingsResponse(null)
      );
      const invalidate = jest.spyOn(queryClient, 'invalidateQueries');
      const hook = renderHook(() => useUpdateAppearance(), {
        wrapper: wrapper(queryClient),
      });
      return { queryClient, invalidate, ...hook };
    }

    beforeEach(() => {
      root.removeAttribute(PALETTE_ATTRIBUTE);
    });

    it('PATCHes only the palette and seeds the settings query', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => settingsResponse('emerald'),
      } as Response);
      const { result, queryClient } = renderAppearance();

      result.current.mutate('emerald');

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/user-settings',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({ theme_palette: 'emerald' }),
        })
      );
      expect(queryClient.getQueryData(userSettingsKeys.detail())).toEqual(
        settingsResponse('emerald')
      );
    });

    it('repaints at once, before the save lands', () => {
      mockFetch.mockReturnValueOnce(new Promise(() => {}));
      const { result } = renderAppearance();

      result.current.mutate('emerald');

      return waitFor(() =>
        expect(root.getAttribute(PALETTE_ATTRIBUTE)).toBe('emerald')
      );
    });

    it('sends the default palette as null', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => settingsResponse(null),
      } as Response);
      const { result } = renderAppearance();

      result.current.mutate('default');

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/user-settings',
        expect.objectContaining({
          body: JSON.stringify({ theme_palette: null }),
        })
      );
    });

    it('leaves the journal and task reads alone', async () => {
      // Unlike a timezone change, a palette changes nothing the server derives.
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => settingsResponse('emerald'),
      } as Response);
      const { result, invalidate } = renderAppearance();

      result.current.mutate('emerald');

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(invalidate).not.toHaveBeenCalled();
    });

    it('cannot be undone by a settings read that lands after it', async () => {
      // A background read started before the save answers with the old value.
      let landStaleRead: (value: unknown) => void = () => {};
      const { result, queryClient } = renderAppearance();
      const staleRead = queryClient
        .fetchQuery({
          queryKey: userSettingsKeys.detail(),
          queryFn: () =>
            new Promise(resolve => {
              landStaleRead = resolve;
            }),
          staleTime: 0,
        })
        .catch(() => undefined);
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => settingsResponse('emerald'),
      } as Response);

      result.current.mutate('emerald');
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      landStaleRead(settingsResponse(null));
      await staleRead;

      expect(
        queryClient.getQueryData<UserSettingsResponse>(
          userSettingsKeys.detail()
        )?.data.attributes.theme_palette
      ).toBe('emerald');
    });

    it('keeps the fields the localisation card saved meanwhile', async () => {
      let answer: (value: Response) => void = () => {};
      mockFetch.mockReturnValueOnce(
        new Promise<Response>(resolve => {
          answer = resolve;
        })
      );
      const { result, queryClient } = renderAppearance();

      result.current.mutate('emerald');
      // The other card saves a new zone while the palette PATCH is in flight.
      queryClient.setQueryData<UserSettingsResponse>(
        userSettingsKeys.detail(),
        old => ({
          ...old!,
          data: {
            ...old!.data,
            attributes: { ...old!.data.attributes, timezone: 'Europe/Paris' },
          },
        })
      );
      // The palette response predates that save.
      answer({
        ok: true,
        json: async () => settingsResponse('emerald'),
      } as Response);
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      const attributes = queryClient.getQueryData<UserSettingsResponse>(
        userSettingsKeys.detail()
      )?.data.attributes;
      expect(attributes?.timezone).toBe('Europe/Paris');
      expect(attributes?.theme_palette).toBe('emerald');
    });

    it('puts the previous palette back when the save fails', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ errors: [{ detail: 'boom' }] }),
      } as Response);
      const { result } = renderAppearance();

      result.current.mutate('emerald');

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(root.hasAttribute(PALETTE_ATTRIBUTE)).toBe(false);
    });
  });

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
});
