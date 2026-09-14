/**
 * @jest-environment jsdom
 */

import {
  QueryClient,
  QueryClientProvider,
  focusManager,
  useMutation,
} from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { createQueryTestHarness } from '@/test-utils';
import { QUERY_CLIENT_DEFAULT_OPTIONS } from '@/lib/query-client-options';
import {
  homeDashboardKeys,
  isSettledDashboardRead,
  useAnchorDayRefresh,
  useHomeDashboard,
} from '../home-dashboard';
import { TASK_WRITE_KEY } from '../tasks';
import { useObtainTodaySummaryOnLoad } from '../today-summary-on-load';
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

  /**
   * Raised in review on PR #1434. A boundary further off than a `setTimeout`
   * can hold cannot be waited for in one go, and the obvious fix — cap the
   * delay — invalidates **early**: the refetch returns the same anchor, the
   * effect does not re-run, and the page is left with no timer at all. The
   * wait is taken in instalments instead, and only a timer that actually
   * reached the boundary invalidates.
   */
  it('waits in instalments for a boundary a single timer cannot reach', async () => {
    const MAX_TIMEOUT = 2_147_483_647;
    // A browser clock the better part of a year behind the anchor.
    jest.setSystemTime(new Date('2026-01-01T03:00:00Z'));
    const boundary = new Date('2026-07-31T14:00:00Z');

    const { result } = renderPageLikeCaller(ANCHOR);
    await settle(result);

    // One whole timer's worth of waiting, and still nothing: the page must not
    // spend its one rescheduling opportunity before the day has ended.
    await act(async () => {
      jest.advanceTimersByTime(MAX_TIMEOUT);
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // The rest of the way, through however many further instalments it takes.
    await act(async () => {
      jest.advanceTimersByTime(boundary.getTime() - Date.now());
    });
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

/**
 * The card's one automatic request (ITER18-005 Phase 8): once per mount and anchor day,
 * when the first settled read of today has no prose, read today's summary —
 * which is what generates a missing, invalidated or stale one — and read the
 * dashboard back.
 *
 * Run against a client built from the **production** defaults. The shared test
 * harness turns retries off, and so would hide the two ways this hook could
 * regenerate underneath a reader: a retried read, and a query refetched on
 * focus.
 */
/**
 * One answer to "has this visit read the dashboard?", shared by the card's
 * read on load and its hold (Augment review on PR #1470). A read with a fetch in
 * flight is not settled, and neither is one whose refetch failed: React Query
 * keeps the cached payload on an error, so data alone says nothing about this
 * visit.
 */
describe('isSettledDashboardRead', () => {
  it('is settled once a read has succeeded with nothing in flight', () => {
    expect(
      isSettledDashboardRead({
        isSuccess: true,
        isFetching: false,
        isFetchedAfterMount: true,
      })
    ).toBe(true);
  });

  it('is not settled while a read is in flight', () => {
    expect(
      isSettledDashboardRead({
        isSuccess: true,
        isFetching: true,
        isFetchedAfterMount: true,
      })
    ).toBe(false);
  });

  it('is not settled on a cached read this mount did not make, however fresh', () => {
    expect(
      isSettledDashboardRead({
        isSuccess: true,
        isFetching: false,
        isFetchedAfterMount: false,
      })
    ).toBe(false);
  });

  it('is not settled when the latest read failed, whatever data is cached', () => {
    expect(
      isSettledDashboardRead({
        isSuccess: false,
        isFetching: false,
        isFetchedAfterMount: true,
      })
    ).toBe(false);
  });
});

describe('useObtainTodaySummaryOnLoad', () => {
  const ANCHOR = '2026-07-29';
  const SUMMARY_URL = `/api/journals/daily-summary/${ANCHOR}`;
  // 13:00 in Sydney on the anchor day, so the anchor is live.
  const ON_THE_ANCHOR_DAY = new Date(`${ANCHOR}T03:00:00Z`);

  const GENERATING_SECTION = {
    status: DashboardSectionStatus.READY,
    data: {
      state: DashboardSummaryState.GENERATING,
      summary_text: null,
      journal_count: 3,
      event_count: 2,
      contact_count: 4,
      mood_average: 7.5,
    },
  } as const;
  const UNAVAILABLE_SECTION = {
    status: DashboardSectionStatus.UNAVAILABLE,
    data: null,
  } as const;

  /** What `GET /api/journals/daily-summary/{date}` answers when it has a row. */
  const SUMMARY_ROW = {
    data: {
      type: 'journal-daily-summaries',
      id: `user-1:${ANCHOR}`,
      attributes: {
        summary_date: ANCHOR,
        summary_text: 'Obtained on load.',
        journal_count: 1,
        event_count: 0,
        contact_count: 0,
        mood_average: null,
        status: 'generated',
      },
    },
  };

  function summaryRowResponse(): Response {
    return { ok: true, json: async () => SUMMARY_ROW } as Response;
  }

  let served: HomeDashboardResponse;
  let summaryResponse: () => Promise<Response>;

  function withSummary(
    summary: HomeDashboardResponse['data']['attributes']['summary']
  ): HomeDashboardResponse {
    const document = makeDashboardResponse();
    document.data.attributes.summary = summary;
    return document;
  }

  function callsTo(url: string): number {
    return mockFetch.mock.calls.filter(([input]) => String(input) === url)
      .length;
  }

  function productionHarness() {
    const queryClient = new QueryClient({
      defaultOptions: QUERY_CLIENT_DEFAULT_OPTIONS,
    });
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    return { queryClient, wrapper };
  }

  function renderOnLoad(harness = productionHarness()) {
    const view = renderHook(
      () => ({
        dashboard: useHomeDashboard(),
        obtain: useObtainTodaySummaryOnLoad(),
      }),
      { wrapper: harness.wrapper }
    );
    return { ...view, queryClient: harness.queryClient };
  }

  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(ON_THE_ANCHOR_DAY);
    mockFetch.mockReset();
    served = makeDashboardResponse();
    summaryResponse = () => Promise.resolve(summaryRowResponse());
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === DASHBOARD_URL) {
        const document = served;
        return Promise.resolve({
          ok: true,
          json: async () => document,
        } as Response);
      }
      if (url === SUMMARY_URL) {
        return summaryResponse();
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('reads today’s summary once when the first read is generating, then reads the dashboard back', async () => {
    served = withSummary(GENERATING_SECTION);

    renderOnLoad();

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBe(2));
    expect(mockFetch).toHaveBeenCalledWith(SUMMARY_URL, {
      credentials: 'include',
    });
  });

  it('reads it once when the first read has no summary at all', async () => {
    served = withSummary(UNAVAILABLE_SECTION);

    renderOnLoad();

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
  });

  it('reads nothing when the first read already has prose', async () => {
    const { result } = renderOnLoad();

    await waitFor(() => expect(result.current.dashboard.isSuccess).toBe(true));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(5000);
    });

    expect(callsTo(SUMMARY_URL)).toBe(0);
    expect(result.current.obtain.isObtaining).toBe(false);
  });

  it('reads nothing for an anchor day that has already ended', async () => {
    served = withSummary(GENERATING_SECTION);
    served.meta.anchor.date = '2026-07-28';

    const { result } = renderOnLoad();

    await waitFor(() => expect(result.current.dashboard.isSuccess).toBe(true));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(5000);
    });

    expect(callsTo(SUMMARY_URL)).toBe(0);
    expect(result.current.obtain.isObtaining).toBe(false);
  });

  it('does not read again when a later read of the same day reports it generating', async () => {
    const { result, queryClient } = renderOnLoad();
    await waitFor(() => expect(result.current.dashboard.isSuccess).toBe(true));

    // What a task tick's refetch looks like once the tick has invalidated today.
    served = withSummary(GENERATING_SECTION);
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: homeDashboardKeys.all });
    });
    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBe(2));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(5000);
    });

    expect(callsTo(SUMMARY_URL)).toBe(0);
  });

  it('does not refetch the summary when the window regains focus', async () => {
    served = withSummary(GENERATING_SECTION);
    renderOnLoad();
    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));

    await act(async () => {
      await jest.advanceTimersByTimeAsync(10 * 60 * 1000);
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });

    expect(callsTo(SUMMARY_URL)).toBe(1);
  });

  it('decides on a read fetched after mount, not on a stale cached one', async () => {
    const harness = productionHarness();
    harness.queryClient.setQueryData(
      homeDashboardKeys.all,
      makeDashboardResponse(),
      { updatedAt: Date.now() - 10 * 60 * 1000 }
    );
    served = withSummary(GENERATING_SECTION);

    renderOnLoad(harness);

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
  });

  it('reads nothing from a stale cached read whose refetch fails', async () => {
    const harness = productionHarness();
    harness.queryClient.setQueryData(
      homeDashboardKeys.all,
      withSummary(GENERATING_SECTION),
      { updatedAt: Date.now() - 10 * 60 * 1000 }
    );
    // Every read of the dashboard fails, retries included, so the only data this
    // visit holds is the previous visit's.
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === DASHBOARD_URL) {
        return Promise.resolve({
          ok: false,
          json: async () => ({ errors: [{ detail: 'Dashboard unavailable' }] }),
        } as Response);
      }
      if (url === SUMMARY_URL) {
        return summaryResponse();
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    const { result } = renderOnLoad(harness);

    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBeGreaterThan(0));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(60 * 1000);
    });

    expect(result.current.dashboard.isError).toBe(true);
    expect(callsTo(SUMMARY_URL)).toBe(0);
    expect(result.current.obtain.isObtaining).toBe(false);
  });

  it('reads again on a remount that comes back before the last read is evicted', async () => {
    served = withSummary(GENERATING_SECTION);
    const harness = productionHarness();

    const first = renderOnLoad(harness);
    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
    await waitFor(() =>
      expect(first.result.current.obtain.isObtaining).toBe(false)
    );
    first.unmount();

    // Straight back, with the fake clock not advanced: the previous read's
    // eviction timer has not run, so a key shared across mounts would answer
    // from it and this load would read nothing. The dashboard is read again on
    // the way in, as the page's refetch on mount does, because the decision
    // waits for a read this mount made.
    const second = renderOnLoad(harness);
    await act(async () => {
      await harness.queryClient.invalidateQueries({
        queryKey: homeDashboardKeys.all,
      });
    });

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(2));
    await waitFor(() =>
      expect(second.result.current.obtain.isObtaining).toBe(false)
    );
  });

  /**
   * A remount within the stale time renders a fresh cached payload and fetches
   * nothing, so this visit has read nothing (Augment review on PR #1470). The
   * decision waits for a read this mount made — on the page, its refetch on
   * mount.
   */
  it('decides only on a read this mount made, not on a fresh cached one', async () => {
    const harness = productionHarness();
    harness.queryClient.setQueryData(
      homeDashboardKeys.all,
      withSummary(GENERATING_SECTION)
    );
    served = withSummary(GENERATING_SECTION);

    const { queryClient } = renderOnLoad(harness);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(5000);
    });
    expect(callsTo(DASHBOARD_URL)).toBe(0);
    expect(callsTo(SUMMARY_URL)).toBe(0);

    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: homeDashboardKeys.all });
    });

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
  });

  it('is obtaining from the first render that holds the read', async () => {
    served = withSummary(GENERATING_SECTION);
    summaryResponse = () => new Promise<Response>(() => {});
    const renders: { hasData: boolean; isObtaining: boolean }[] = [];

    renderHook(
      () => {
        const dashboard = useHomeDashboard();
        const { isObtaining } = useObtainTodaySummaryOnLoad();
        renders.push({ hasData: dashboard.data !== undefined, isObtaining });
      },
      { wrapper: productionHarness().wrapper }
    );

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
    const withData = renders.filter(render => render.hasData);
    expect(withData.length).toBeGreaterThan(0);
    expect(withData.every(render => render.isObtaining)).toBe(true);
  });

  it('settles once the dashboard has been read back after the summary', async () => {
    served = withSummary(GENERATING_SECTION);

    const { result } = renderOnLoad();

    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBe(2));
    await waitFor(() => expect(result.current.obtain.isObtaining).toBe(false));
  });

  it('neither retries nor throws when the summary read fails', async () => {
    served = withSummary(GENERATING_SECTION);
    summaryResponse = () =>
      Promise.resolve({
        ok: false,
        json: async () => ({ errors: [{ detail: 'AI provider unavailable' }] }),
      } as Response);

    const { result } = renderOnLoad();

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(60 * 1000);
    });

    expect(callsTo(SUMMARY_URL)).toBe(1);
    expect(result.current.obtain.isObtaining).toBe(false);
  });

  it('settles without reading the dashboard back when there is no summary to read', async () => {
    served = withSummary(UNAVAILABLE_SECTION);
    // An unconfigured AI answers with no row: nothing changed, so a read-back
    // would cost a request and draw the same page.
    summaryResponse = () =>
      Promise.resolve({
        ok: true,
        json: async () => ({ data: null }),
      } as Response);

    const { result } = renderOnLoad();

    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));
    await waitFor(() => expect(result.current.obtain.isObtaining).toBe(false));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(5000);
    });

    expect(callsTo(DASHBOARD_URL)).toBe(1);
  });

  it('settles even when reading the dashboard back fails', async () => {
    served = withSummary(GENERATING_SECTION);
    let dashboardReads = 0;
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === DASHBOARD_URL) {
        dashboardReads += 1;
        const document = served;
        // The first read succeeds; every read after it fails, retries included.
        return Promise.resolve(
          dashboardReads === 1
            ? ({ ok: true, json: async () => document } as Response)
            : ({
                ok: false,
                json: async () => ({
                  errors: [{ detail: 'Dashboard unavailable' }],
                }),
              } as Response)
        );
      }
      if (url === SUMMARY_URL) {
        return summaryResponse();
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    const { result } = renderOnLoad();

    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBeGreaterThan(1));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(60 * 1000);
    });

    await waitFor(() => expect(result.current.obtain.isObtaining).toBe(false));
  });

  it('holds the read-back while a task write is in flight, then reads back once it settles', async () => {
    served = withSummary(GENERATING_SECTION);
    let resolveSummary: (response: Response) => void = () => {};
    summaryResponse = () =>
      new Promise<Response>(resolve => {
        resolveSummary = resolve;
      });
    let settleWrite: () => void = () => {};

    const { result } = renderHook(
      () => ({
        obtain: useObtainTodaySummaryOnLoad(),
        write: useMutation({
          mutationKey: TASK_WRITE_KEY,
          mutationFn: (_variables: { taskId: string }) =>
            new Promise<void>(resolve => {
              settleWrite = resolve;
            }),
        }),
      }),
      { wrapper: productionHarness().wrapper }
    );
    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));

    // A tick in flight: a read-back landing before it settles would answer from
    // a server that has not processed it, and put back the row it removed.
    act(() => {
      result.current.write.mutate({ taskId: '31' });
    });
    await act(async () => {
      resolveSummary(summaryRowResponse());
      await jest.advanceTimersByTimeAsync(1000);
    });

    expect(callsTo(DASHBOARD_URL)).toBe(1);
    expect(result.current.obtain.isObtaining).toBe(true);

    await act(async () => {
      settleWrite();
      await jest.advanceTimersByTimeAsync(1000);
    });

    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBe(2));
    await waitFor(() => expect(result.current.obtain.isObtaining).toBe(false));
  });

  it('does not hold the read-back for an unrelated mutation that takes a string id', async () => {
    served = withSummary(GENERATING_SECTION);
    let resolveSummary: (response: Response) => void = () => {};
    summaryResponse = () =>
      new Promise<Response>(resolve => {
        resolveSummary = resolve;
      });

    // A journal, tag or series deletion takes a bare id, exactly as deleting a
    // task does — and is not a task write.
    const { result } = renderHook(
      () => ({
        obtain: useObtainTodaySummaryOnLoad(),
        write: useMutation({
          mutationFn: (_journalId: string) => new Promise<void>(() => {}),
        }),
      }),
      { wrapper: productionHarness().wrapper }
    );
    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));

    act(() => {
      result.current.write.mutate('55');
    });
    await act(async () => {
      resolveSummary(summaryRowResponse());
    });

    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBe(2));
    await waitFor(() => expect(result.current.obtain.isObtaining).toBe(false));
  });

  it('does not hold the read-back for a write that is not a task’s', async () => {
    served = withSummary(GENERATING_SECTION);
    let resolveSummary: (response: Response) => void = () => {};
    summaryResponse = () =>
      new Promise<Response>(resolve => {
        resolveSummary = resolve;
      });

    const { result } = renderHook(
      () => ({
        obtain: useObtainTodaySummaryOnLoad(),
        write: useMutation({
          mutationFn: (_variables: { contactId: string }) =>
            new Promise<void>(() => {}),
        }),
      }),
      { wrapper: productionHarness().wrapper }
    );
    await waitFor(() => expect(callsTo(SUMMARY_URL)).toBe(1));

    act(() => {
      result.current.write.mutate({ contactId: 'contact-7' });
    });
    await act(async () => {
      resolveSummary(summaryRowResponse());
    });

    await waitFor(() => expect(callsTo(DASHBOARD_URL)).toBe(2));
    await waitFor(() => expect(result.current.obtain.isObtaining).toBe(false));
  });
});
