/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness } from '@/test-utils';
import { useAnchorDayRefresh, useHomeDashboard } from '../home-dashboard';
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
        agenda: {
          status: DashboardSectionStatus.READY,
          data: { entries: [], tomorrow: { date: '2026-07-30', entries: [] } },
        },
        tasks: {
          status: DashboardSectionStatus.READY,
          // A window and a total since Phase 13; `{}` would be a shape the
          // endpoint cannot produce.
          data: {
            window: {
              start_date: '2026-07-29',
              end_date: '2026-08-05',
              days_ahead: 7,
            },
            total: 0,
            tasks: [],
          },
        },
        upcoming_dates: {
          status: DashboardSectionStatus.UNAVAILABLE,
          data: null,
        },
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

/**
 * The refresh at the anchor day's end (ITER18-004 Phase 16, inherited from
 * Phase 3).
 *
 * When the boundary falls is `msUntilNextAnchorDay`'s and is pinned in
 * `dashboard-anchor.test.ts`, DST cases included. What is pinned here is that a
 * timer is actually set for it, that it fires **then and not before**, and that
 * it is cleaned up — because a scheduler that never fired would look identical
 * on screen to one that worked, right up until the night somebody left the page
 * open.
 *
 * Two things about driving this with fake timers, both learned the hard way.
 * `waitFor` **advances them itself** while it polls, so "just before the
 * boundary" has to be measured against the clock rather than assumed from the
 * start of the test. And an invalidation that lands while the first fetch is
 * still in flight is deduped rather than issuing a second request, so a test
 * about the *stale-anchor* case has to let the first read finish before the
 * stale anchor arrives — which is also the only way the case occurs in life,
 * since the anchor that has gone stale is one the page is already holding.
 */
describe('useAnchorDayRefresh', () => {
  const SYDNEY = 'Australia/Sydney';
  const ANCHOR = { date: '2026-07-31', timezone: SYDNEY };
  /** 13:00 in Sydney on the anchor day. */
  const MIDDAY = new Date('2026-07-31T03:00:00Z');
  /** Midnight in Sydney at the end of it. */
  const BOUNDARY = new Date('2026-07-31T14:00:00Z');
  const ONE_DAY = 24 * 60 * 60 * 1000;

  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => makeDashboardResponse(),
    } as Response);
    jest.useFakeTimers();
    jest.setSystemTime(MIDDAY);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  /** The page's arrangement: one caller reading the query, one scheduling. */
  function renderPageLikeCaller(anchor: typeof ANCHOR | undefined) {
    return renderHook(
      ({ current }: { current: typeof ANCHOR | undefined }) => {
        const query = useHomeDashboard();
        useAnchorDayRefresh(current);
        return query;
      },
      { wrapper: harness.wrapper, initialProps: { current: anchor } }
    );
  }

  async function settle(result: {
    current: { isSuccess: boolean };
  }): Promise<void> {
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  }

  /** Fake time forward to `instant`, measured from the clock as it now reads. */
  async function advanceTo(instant: Date, offsetMs = 0): Promise<void> {
    await act(async () => {
      jest.advanceTimersByTime(instant.getTime() + offsetMs - Date.now());
    });
  }

  it('leaves the query alone until the anchor day actually ends', async () => {
    const { result } = renderPageLikeCaller(ANCHOR);
    await settle(result);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    await advanceTo(BOUNDARY, -1000);

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('refetches the moment it does', async () => {
    const { result } = renderPageLikeCaller(ANCHOR);
    await settle(result);

    await advanceTo(BOUNDARY);

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
  });

  /**
   * A payload the page is already holding when its day ends — the shape the
   * cache takes when a tab is left open, or when React Query serves a cached
   * read from before midnight. Due at once, and it terminates: the effect is
   * keyed on the anchor, so a refetch that returns the same day schedules
   * nothing further.
   */
  it('refreshes immediately for an anchor that has already passed', async () => {
    const { result, rerender } = renderPageLikeCaller(ANCHOR);
    await settle(result);

    rerender({ current: { date: '2026-07-30', timezone: SYDNEY } });
    await act(async () => {
      jest.advanceTimersByTime(0);
    });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    // The anchor it is holding has not moved, so nothing else is scheduled.
    await act(async () => {
      jest.advanceTimersByTime(ONE_DAY * 2);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('schedules nothing while there is no anchor to schedule against', async () => {
    const { result } = renderPageLikeCaller(undefined);
    await settle(result);

    await act(async () => {
      jest.advanceTimersByTime(ONE_DAY * 2);
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('schedules nothing for an anchor day it cannot read', async () => {
    const { result } = renderPageLikeCaller({
      date: 'not-a-date',
      timezone: SYDNEY,
    });
    await settle(result);

    await act(async () => {
      jest.advanceTimersByTime(ONE_DAY * 2);
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('moves the timer when the payload\u2019s anchor moves', async () => {
    const { result, rerender } = renderPageLikeCaller(ANCHOR);
    await settle(result);

    // A new day arrives: yesterday's timer must not survive it, or the page
    // would refresh at a boundary that has already gone by.
    rerender({ current: { date: '2026-08-01', timezone: SYDNEY } });

    await advanceTo(BOUNDARY);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    await advanceTo(new Date(BOUNDARY.getTime() + ONE_DAY));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
  });

  it('clears the timer when the page goes away', async () => {
    const { result, unmount } = renderPageLikeCaller(ANCHOR);
    await settle(result);

    unmount();

    await act(async () => {
      jest.advanceTimersByTime(ONE_DAY * 2);
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
