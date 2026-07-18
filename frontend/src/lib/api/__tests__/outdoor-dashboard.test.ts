/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness } from '@/test-utils';
import { useOutdoorDashboard } from '../outdoor-dashboard';
import type { OutdoorDashboardResponse } from '../outdoor-dashboard';
import { JournalType } from '@/types/journals';

// Mock fetch
globalThis.fetch = jest.fn();

// jest.setup.ts mocks @/lib/constants but omits the outdoor-dashboard
// endpoint; use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const DASHBOARD_URL = '/api/journals/outdoor-dashboard';

function makeDashboardResponse(): OutdoorDashboardResponse {
  return {
    data: {
      type: 'outdoor-dashboards',
      id: 'user-1',
      attributes: {
        upcoming_activities: [
          {
            journal_id: 42,
            title: 'Empress Falls Canyon',
            event_date_range: {
              start: '2026-07-20T12:00:00Z',
              end: '2026-07-20T18:00:00Z',
            },
            subtypes: [JournalType.CANYONING],
            is_planning: false,
          },
        ],
        checked_out_gear: [
          {
            gear_item_id: 'gear-1',
            name: 'Static rope 60m',
            checked_out_since: '2026-07-10T12:00:00Z',
            journal_id: 7,
          },
        ],
        activity_totals: {
          last_30_days: { [JournalType.CANYONING]: 1 },
          last_365_days: { [JournalType.CANYONING]: 3 },
        },
        templates_done: {
          canyoning: [
            {
              template_id: 'tpl-empress',
              name: 'Empress Falls',
              done_count: 3,
            },
          ],
        },
      },
    },
  };
}

describe('useOutdoorDashboard', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('fetches the outdoor dashboard with credentials and returns the parsed data', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => makeDashboardResponse(),
    } as Response);

    const { result } = renderHook(() => useOutdoorDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(DASHBOARD_URL, {
      credentials: 'include',
    });
    const attributes = result.current.data?.data.attributes;
    expect(attributes?.upcoming_activities).toHaveLength(1);
    expect(attributes?.upcoming_activities[0].journal_id).toBe(42);
    expect(attributes?.activity_totals.last_365_days).toEqual({
      [JournalType.CANYONING]: 3,
    });
    expect(attributes?.checked_out_gear).toHaveLength(1);
    expect(attributes?.checked_out_gear[0]).toEqual({
      gear_item_id: 'gear-1',
      name: 'Static rope 60m',
      checked_out_since: '2026-07-10T12:00:00Z',
      journal_id: 7,
    });
    expect(attributes?.templates_done.canyoning).toEqual([
      { template_id: 'tpl-empress', name: 'Empress Falls', done_count: 3 },
    ]);
  });

  it('surfaces the JSON API error detail on failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ errors: [{ detail: 'Session expired' }] }),
    } as Response);

    const { result } = renderHook(() => useOutdoorDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error?.message).toBe('Session expired');
  });
});
