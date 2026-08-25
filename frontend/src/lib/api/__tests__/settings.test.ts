/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';

import {
  fetchUserSettings,
  updateTimezone,
  useUpdateTimezone,
} from '../settings';
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

  describe('useUpdateTimezone', () => {
    /**
     * Changing the zone changes what "today" is, and two answers are *derived*
     * from that rather than stored: whether a task has lapsed, and the journal
     * list's `tasks_due_count`, which is the same rule over a whole page. Both
     * sit behind the app-wide five-minute `staleTime`, so a mutation that named
     * only its own namespace would leave the user looking at verdicts reached
     * in the zone they have just corrected.
     */
    function wrapper(client: QueryClient) {
      return function Wrapper({ children }: { children: ReactNode }) {
        return React.createElement(QueryClientProvider, { client }, children);
      };
    }

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
  });
});
