/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness } from '@/test-utils';
import { useHomeDashboard } from '../home-dashboard';
import type { HomeDashboardResponse } from '../home-dashboard';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
} from '../home-dashboard';

// Mock fetch
globalThis.fetch = jest.fn();

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const DASHBOARD_URL = '/api/home-dashboard';

/**
 * A dashboard document in the shape Phases 1 and 2 ship: four sections in
 * their envelopes, the anchor in `meta`.
 */
function makeDashboardResponse(): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: {
          status: DashboardSectionStatus.READY,
          data: {
            state: DashboardSummaryState.GENERATED,
            summary_text: 'A quiet Wednesday.',
            journal_count: 3,
            event_count: 2,
            contact_count: 4,
            mood_average: 7.5,
          },
        },
        agenda: { status: DashboardSectionStatus.READY, data: {} },
        tasks: { status: DashboardSectionStatus.READY, data: {} },
        upcoming_dates: { status: DashboardSectionStatus.READY, data: {} },
      },
    },
    meta: {
      anchor: { date: '2026-07-29', timezone: 'Australia/Sydney' },
    },
  };
}

describe('useHomeDashboard', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('fetches the home dashboard with credentials and returns the parsed data', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => makeDashboardResponse(),
    } as Response);

    const { result } = renderHook(() => useHomeDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(DASHBOARD_URL, {
      credentials: 'include',
    });

    const attributes = result.current.data?.data.attributes;
    expect(result.current.data?.data.type).toBe('home-dashboards');
    expect(attributes?.summary.status).toBe(DashboardSectionStatus.READY);
    expect(attributes?.summary.data?.state).toBe(
      DashboardSummaryState.GENERATED
    );
    expect(attributes?.summary.data?.summary_text).toBe('A quiet Wednesday.');
    expect(attributes?.summary.data?.mood_average).toBe(7.5);
  });

  it('carries the anchor day and zone from meta, which is where the page reads its date', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => makeDashboardResponse(),
    } as Response);

    const { result } = renderHook(() => useHomeDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.meta.anchor).toEqual({
      date: '2026-07-29',
      timezone: 'Australia/Sydney',
    });
  });

  it('reads an unavailable section as a null payload rather than an error', async () => {
    // The Phase 1 contract: `unavailable` means "nothing to show here",
    // whether it could not be read or there is none — never a failed request.
    const document = makeDashboardResponse();
    document.data.attributes.summary = {
      status: DashboardSectionStatus.UNAVAILABLE,
      data: null,
    };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => document,
    } as Response);

    const { result } = renderHook(() => useHomeDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const summary = result.current.data?.data.attributes.summary;
    expect(summary?.status).toBe(DashboardSectionStatus.UNAVAILABLE);
    expect(summary?.data).toBeNull();
    expect(result.current.isError).toBe(false);
  });

  it('surfaces the JSON API error detail on failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ errors: [{ detail: 'Session expired' }] }),
    } as Response);

    const { result } = renderHook(() => useHomeDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error?.message).toBe('Session expired');
  });

  it('falls back to the shared fetch-failed message when the body carries no detail', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => {
        throw new Error('not json');
      },
    } as unknown as Response);

    const { result } = renderHook(() => useHomeDashboard(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error?.message).toBe(
      'Failed to fetch data. Please try again.'
    );
  });

  it('serves concurrent mounts from one fetch, so the page is one round trip', async () => {
    // The acceptance criterion the whole shell rests on: the header and the
    // three section cards all call this hook, and must not each fetch.
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => makeDashboardResponse(),
    } as Response);

    const { result } = renderHook(
      () => ({
        header: useHomeDashboard(),
        agenda: useHomeDashboard(),
        tasks: useHomeDashboard(),
        dates: useHomeDashboard(),
      }),
      { wrapper: harness.wrapper }
    );

    await waitFor(() => expect(result.current.header.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.dates.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
