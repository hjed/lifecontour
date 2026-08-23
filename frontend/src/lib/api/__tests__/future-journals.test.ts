/**
 * @jest-environment jsdom
 */

/**
 * Tests for `useFutureJournals` — the read behind the retarget picker.
 *
 * The hook is a thin shell over `futureJournalOptions`, which owns the filter
 * and the ordering and has its own pure suite. What is asserted here is the
 * shell: the request it issues, where the timezone it judges by comes from,
 * and that the answer arrives already filtered and ordered.
 *
 * The bounded forward window is the part worth understanding. `GET
 * /api/journals` answers `ORDER BY event_date_range_start DESC` and takes no
 * `sort` parameter, so asking for "every journal from today" and taking the
 * first page would return the *furthest* future journals and hide the nearest
 * ones — the opposite of what a picker needs. A dated window is what makes the
 * page it returns the page worth sorting.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness } from '@/test-utils';
import { useFutureJournals } from '../journals';
import { addDaysToIsoDate, todayIn } from '@/lib/future-journals';
import { JournalType } from '@/types/journals';
import type { JournalResource } from '@/types/journals';

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const SYDNEY = 'Australia/Sydney';

function journal(id: string, start: string): JournalResource {
  return {
    id,
    type: 'journals',
    attributes: {
      title: `Journal ${id}`,
      content: '',
      event_date_range: { start, end: start },
      types: [JournalType.NOTE],
      contacts: [],
      tags: [],
    },
  };
}

/** A journal `days` days ahead of today in `timezone`, at local midday. */
function daysAhead(
  id: string,
  days: number,
  timezone = SYDNEY
): JournalResource {
  const date = addDaysToIsoDate(todayIn(timezone), days);
  return journal(id, `${date}T12:00:00Z`);
}

/**
 * Answer the settings read with `timezone`, **and** seed the localStorage cache
 * with it.
 *
 * Seeding matters, and getting it wrong hid a flake here for a while. The hook
 * judges its window with the cached zone until the settings read lands, so a
 * cache disagreeing with the response produces *two* query keys and two walks —
 * and the first request, which most of these assertions read, is then judged in
 * the wrong zone. Under a machine set to `Australia/Sydney` the two zones give
 * the same date for fourteen hours a day and different ones for the other ten,
 * which is a test that passes all afternoon and fails overnight. The cache is
 * what the settings UI keeps in step with the server, so agreeing here is also
 * the honest case.
 */
function settingsRespondWith(timezone: string) {
  localStorage.setItem('pms-default-timezone', timezone);
  mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/user-settings')) {
      return {
        ok: true,
        json: async () => ({
          data: { type: 'user-settings', id: 'u1', attributes: { timezone } },
        }),
      } as Response;
    }
    return {
      ok: true,
      json: async () => ({ data: [], meta: { total: 0 } }),
    } as Response;
  });
}

/**
 * A listing that overflows a page, answered the way the endpoint does: DESC by
 * start date, so the **nearest** journals are on the last page.
 */
function pagedRespondWith(
  pages: Record<number, JournalResource[]>,
  pageCount: number
) {
  localStorage.setItem('pms-default-timezone', 'UTC');
  mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/user-settings')) {
      return {
        ok: true,
        json: async () => ({
          data: {
            type: 'user-settings',
            id: 'u1',
            attributes: { timezone: 'UTC' },
          },
        }),
      } as Response;
    }
    const page = Number(
      new URL(url, 'http://localhost').searchParams.get('page') ?? '1'
    );
    return {
      ok: true,
      json: async () => ({
        data: pages[page] ?? [],
        meta: { page_count: pageCount, current_page: page, per_page: 100 },
      }),
    } as Response;
  });
}

/** Every page number the hook asked the journals endpoint for, in order. */
function requestedPages(): number[] {
  return mockFetch.mock.calls
    .map(([input]) => String(input))
    .filter(url => url.includes('/api/journals'))
    .map(url =>
      Number(new URL(url, 'http://localhost').searchParams.get('page') ?? '1')
    );
}

/** The journals request the hook issued, as a parsed URL. */
function journalsRequestUrl(): URL {
  const call = mockFetch.mock.calls.find(([input]) => {
    const url = String(input);
    return url.includes('/api/journals') && !url.includes('user-settings');
  });
  if (!call) throw new Error('no journals request was issued');
  return new URL(String(call[0]), 'http://localhost');
}

describe('useFutureJournals', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  /**
   * Ninety days is the window; ninety-**one** is what is asked for. `end_date`
   * is a bare date, and the backend reads a bare date as the end of that day in
   * **UTC**, so for a user behind UTC the later hours of their own day-90 fall
   * past the cutoff and would be dropped from a window advertised as ninety
   * days. The largest offset in use is UTC-12, so one day covers every zone,
   * and overshooting the far edge costs nothing — nothing downstream trims by
   * it.
   */
  it('asks for journals from today forward, a day past the 90-day window', async () => {
    settingsRespondWith('UTC');

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = journalsRequestUrl();
    const today = todayIn('UTC');
    expect(url.searchParams.get('start_date')).toBe(today);
    expect(url.searchParams.get('end_date')).toBe(addDaysToIsoDate(today, 91));
  });

  /**
   * Stated as its own assertion because the slack is easy to read as an
   * off-by-one and delete: a journal at the far edge of the window, in a zone
   * behind UTC, is exactly what it is there for.
   */
  it('reaches a journal late on the last day of the window in a zone behind UTC', async () => {
    const losAngeles = 'America/Los_Angeles';
    settingsRespondWith(losAngeles);
    const lastDay = addDaysToIsoDate(todayIn(losAngeles), 90);
    // 18:00 in Los Angeles on the window's last day is the next day in UTC.
    const lateOnTheLastDay = journal('edge', `${lastDay}T18:00:00-08:00`);

    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/user-settings')) {
        return {
          ok: true,
          json: async () => ({
            data: {
              type: 'user-settings',
              id: 'u1',
              attributes: { timezone: losAngeles },
            },
          }),
        } as Response;
      }
      return {
        ok: true,
        json: async () => ({ data: [lateOnTheLastDay], meta: { total: 1 } }),
      } as Response;
    });

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const requestedEnd = journalsRequestUrl().searchParams.get('end_date');
    expect(requestedEnd).not.toBeNull();
    // The instant the backend would compare against is the end of that day in
    // UTC; the journal's start has to fall inside it.
    expect(new Date(`${requestedEnd}T23:59:59.999Z`).getTime()).toBeGreaterThan(
      new Date(lateOnTheLastDay.attributes.event_date_range.start).getTime()
    );
  });

  /**
   * `start_date` is today rather than tomorrow deliberately. It drives
   * `event_date_range_end >= :start_date`, so it is generous by construction —
   * a journal already under way still matches — and asking for tomorrow would
   * risk dropping a journal starting at local midnight in a zone ahead of UTC,
   * whose stored instant still reads as today. The strictly-after rule is
   * applied here instead, in the zone where it means something.
   */
  it('sends today rather than tomorrow, and filters the boundary itself', async () => {
    settingsRespondWith('UTC');
    const today = todayIn('UTC');
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/user-settings')) {
        return {
          ok: true,
          json: async () => ({
            data: {
              type: 'user-settings',
              id: 'u1',
              attributes: { timezone: 'UTC' },
            },
          }),
        } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          data: [journal('today', `${today}T12:00:00Z`)],
          meta: { total: 1 },
        }),
      } as Response;
    });

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(journalsRequestUrl().searchParams.get('start_date')).toBe(today);
    expect(result.current.data).toEqual([]);
  });

  it('asks for a page large enough that the window is not truncated', async () => {
    settingsRespondWith('UTC');

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(journalsRequestUrl().searchParams.get('limit')).toBe('100');
  });

  it('searches across every future journal, not only the window', async () => {
    settingsRespondWith('UTC');

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(
      () => useFutureJournals({ search: 'kanangra' }),
      { wrapper }
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = journalsRequestUrl();
    expect(url.searchParams.get('search')).toBe('kanangra');
    expect(url.searchParams.get('start_date')).toBe(todayIn('UTC'));
    expect(url.searchParams.get('end_date')).toBeNull();
  });

  it('answers nearest-first, from a newest-first listing', async () => {
    settingsRespondWith(SYDNEY);
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/user-settings')) {
        return {
          ok: true,
          json: async () => ({
            data: {
              type: 'user-settings',
              id: 'u1',
              attributes: { timezone: SYDNEY },
            },
          }),
        } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          data: [daysAhead('far', 40), daysAhead('near', 2)],
          meta: { total: 2 },
        }),
      } as Response;
    });

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.map(option => option.id)).toEqual([
      'near',
      'far',
    ]);
  });

  /**
   * The configured zone is the one the server judges by, so it is the one the
   * hook asks for — not the browser's.
   */
  it('judges the window by the user’s configured timezone', async () => {
    settingsRespondWith(SYDNEY);

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(journalsRequestUrl().searchParams.get('start_date')).toBe(
      todayIn(SYDNEY)
    );
  });

  /**
   * The settings read is a second request and can still be in flight. Falling
   * back to the cached timezone the settings UI writes keeps the first page
   * right for the overwhelmingly common case, and the request is reissued
   * under a new key if the configured zone turns out to differ.
   */
  it('falls back to the cached timezone while the settings read is in flight', async () => {
    localStorage.setItem('pms-default-timezone', SYDNEY);
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/user-settings')) {
        return new Promise<Response>(() => {}); // never settles
      }
      return {
        ok: true,
        json: async () => ({ data: [], meta: { total: 0 } }),
      } as Response;
    });

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(journalsRequestUrl().searchParams.get('start_date')).toBe(
      todayIn(SYDNEY)
    );
  });

  it('surfaces a failed listing rather than an empty one', async () => {
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/user-settings')) {
        return {
          ok: true,
          json: async () => ({
            data: {
              type: 'user-settings',
              id: 'u1',
              attributes: { timezone: 'UTC' },
            },
          }),
        } as Response;
      }
      return {
        ok: false,
        json: async () => ({ errors: [{ detail: 'nope' }] }),
      } as Response;
    });

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  /**
   * The defect this replaced: the listing is `ORDER BY
   * event_date_range_start DESC`, so a first page of 100 is the hundred
   * journals *furthest* away and the near ones — the entire point of the
   * picker — are the ones dropped. Bounding the window caps the far end, not
   * the near one.
   */
  describe('when the window overflows a page', () => {
    it('walks to the last page, where the nearest journals are', async () => {
      const fullLastPage = [
        daysAhead('near', 2, 'UTC'),
        ...Array.from({ length: 99 }, (_, index) =>
          daysAhead(`also-near-${index}`, 3, 'UTC')
        ),
      ];
      pagedRespondWith(
        { 1: [daysAhead('far', 80, 'UTC')], 3: fullLastPage },
        3
      );

      const { wrapper } = createQueryTestHarness();
      const { result } = renderHook(() => useFutureJournals(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(requestedPages()).toEqual([1, 3]);
      expect(result.current.data?.[0].id).toBe('near');
      expect(result.current.data).toHaveLength(100);
    });

    /**
     * A total just past a page boundary leaves the last page holding one or
     * two journals. Offering only those would be a worse answer than the bug
     * this walk exists to fix.
     */
    it('takes the page before it too when the last page is short', async () => {
      const nearlyFull = Array.from({ length: 100 }, (_, index) =>
        daysAhead(`mid-${index}`, 30, 'UTC')
      );
      pagedRespondWith(
        { 1: [], 2: nearlyFull, 3: [daysAhead('near', 2, 'UTC')] },
        3
      );

      const { wrapper } = createQueryTestHarness();
      const { result } = renderHook(() => useFutureJournals(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(requestedPages()).toEqual([1, 3, 2]);
      expect(result.current.data?.[0].id).toBe('near');
      expect(result.current.data).toHaveLength(101);
    });

    it('reaches back to the first page rather than fetching it twice', async () => {
      pagedRespondWith(
        { 1: [daysAhead('far', 80, 'UTC')], 2: [daysAhead('near', 2, 'UTC')] },
        2
      );

      const { wrapper } = createQueryTestHarness();
      const { result } = renderHook(() => useFutureJournals(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(requestedPages()).toEqual([1, 2]);
      expect(result.current.data?.map(option => option.id)).toEqual([
        'near',
        'far',
      ]);
    });

    it('asks once when everything fits on one page', async () => {
      pagedRespondWith({ 1: [daysAhead('near', 2, 'UTC')] }, 1);

      const { wrapper } = createQueryTestHarness();
      const { result } = renderHook(() => useFutureJournals(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(requestedPages()).toEqual([1]);
    });
  });

  /**
   * Every debounced keystroke is a new query key. Without kept data the list
   * is replaced by a loading line on each letter, which is the one thing a
   * search-as-you-type control must not do.
   */
  it('keeps the previous list on screen while a search loads', async () => {
    pagedRespondWith({ 1: [daysAhead('near', 2, 'UTC')] }, 1);

    const { wrapper } = createQueryTestHarness();
    const { result, rerender } = renderHook(
      ({ search }: { search: string }) => useFutureJournals({ search }),
      { wrapper, initialProps: { search: '' } }
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ search: 'kanangra' });

    expect(result.current.data?.map(option => option.id)).toEqual(['near']);
  });

  /**
   * The dialog mounts the picker only while it is open, but the hook is also
   * given an `enabled` switch so a closed picker inside a mounted form costs
   * nothing.
   */
  it('issues no listing request while it is disabled', async () => {
    settingsRespondWith('UTC');

    const { wrapper } = createQueryTestHarness();
    const { result } = renderHook(() => useFutureJournals({ enabled: false }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe('idle'));
    expect(() => journalsRequestUrl()).toThrow(/no journals request/);
  });
});
