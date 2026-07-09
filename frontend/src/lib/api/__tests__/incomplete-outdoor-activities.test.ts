/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { createQueryTestHarness } from '@/test-utils';
import {
  incompleteOutdoorActivityKeys,
  useDismissIncompleteOutdoorActivity,
  useIncompleteOutdoorActivities,
  useUndismissIncompleteOutdoorActivity,
} from '../incomplete-outdoor-activities';
import type { IncompleteOutdoorActivitiesListResponse } from '../incomplete-outdoor-activities';
import { JournalType } from '@/types/journals';

// Mock fetch
globalThis.fetch = jest.fn();

// jest.setup.ts mocks @/lib/constants but omits the incomplete-outdoor-activity
// endpoints; use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

const LIST_URL = '/api/journals/incomplete-outdoor-activities';

function makeListResponse(
  ids: string[]
): IncompleteOutdoorActivitiesListResponse {
  return {
    data: ids.map(id => ({
      type: 'incomplete-outdoor-activities',
      id,
      attributes: {
        title: `Journal ${id}`,
        event_date_range: {
          start: '2026-06-01T12:00:00Z',
          end: '2026-06-01T12:00:00Z',
        },
        subtypes: [JournalType.CANYONING],
        reasons: ['no_participants'],
        dismissed: false,
      },
    })),
  };
}

describe('useIncompleteOutdoorActivities', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('fetches the default list without the include_dismissed param', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => makeListResponse(['1']),
    } as Response);

    const { result } = renderHook(() => useIncompleteOutdoorActivities(), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(LIST_URL, {
      credentials: 'include',
    });
    expect(result.current.data?.data).toHaveLength(1);
  });

  it('fetches with include_dismissed=true when requested', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => makeListResponse(['1']),
    } as Response);

    const { result } = renderHook(() => useIncompleteOutdoorActivities(true), {
      wrapper: harness.wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(
      `${LIST_URL}?include_dismissed=true`,
      {
        credentials: 'include',
      }
    );
  });
});

describe('useDismissIncompleteOutdoorActivity', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('POSTs to the dismiss endpoint and optimistically removes the entry from the default list', async () => {
    harness.queryClient.setQueryData(
      incompleteOutdoorActivityKeys.list(false),
      makeListResponse(['1', '2'])
    );
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    const { result } = renderHook(() => useDismissIncompleteOutdoorActivity(), {
      wrapper: harness.wrapper,
    });

    result.current.mutate('1');

    // Optimistic removal happens before the POST resolves
    await waitFor(() => {
      const cached =
        harness.queryClient.getQueryData<IncompleteOutdoorActivitiesListResponse>(
          incompleteOutdoorActivityKeys.list(false)
        );
      expect(cached?.data.map(entry => entry.id)).toEqual(['2']);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(`${LIST_URL}/1/dismiss`, {
      method: 'POST',
      credentials: 'include',
    });
    expect(toast.success).toHaveBeenCalledWith(
      'Activity dismissed from the incomplete review',
      expect.objectContaining({
        action: expect.objectContaining({ label: 'Undo' }),
      })
    );
  });

  it('restores the cached list and shows an error toast when the POST fails', async () => {
    harness.queryClient.setQueryData(
      incompleteOutdoorActivityKeys.list(false),
      makeListResponse(['1', '2'])
    );
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ errors: [{ detail: 'Journal not found' }] }),
    } as Response);

    const { result } = renderHook(() => useDismissIncompleteOutdoorActivity(), {
      wrapper: harness.wrapper,
    });

    result.current.mutate('1');

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached =
      harness.queryClient.getQueryData<IncompleteOutdoorActivitiesListResponse>(
        incompleteOutdoorActivityKeys.list(false)
      );
    expect(cached?.data.map(entry => entry.id)).toEqual(['1', '2']);
    expect(toast.error).toHaveBeenCalledWith('Journal not found');
  });

  it('POSTs to the undismiss endpoint and invalidates the lists when Undo is clicked', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({}),
    } as Response);
    const invalidateSpy = jest.spyOn(harness.queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useDismissIncompleteOutdoorActivity(), {
      wrapper: harness.wrapper,
    });

    result.current.mutate('1');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const undoAction = toast.success.mock.calls[0][1].action as {
      label: string;
      onClick: () => void;
    };
    undoAction.onClick();

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(`${LIST_URL}/1/undismiss`, {
        method: 'POST',
        credentials: 'include',
      });
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: incompleteOutdoorActivityKeys.lists(),
      });
    });
  });
});

describe('useUndismissIncompleteOutdoorActivity', () => {
  let harness: ReturnType<typeof createQueryTestHarness>;

  beforeEach(() => {
    harness = createQueryTestHarness();
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('POSTs to the undismiss endpoint, toasts success, and invalidates the lists', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);
    const invalidateSpy = jest.spyOn(harness.queryClient, 'invalidateQueries');

    const { result } = renderHook(
      () => useUndismissIncompleteOutdoorActivity(),
      { wrapper: harness.wrapper }
    );

    result.current.mutate('7');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockFetch).toHaveBeenCalledWith(`${LIST_URL}/7/undismiss`, {
      method: 'POST',
      credentials: 'include',
    });
    expect(toast.success).toHaveBeenCalledWith(
      'Activity restored to the incomplete review'
    );
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: incompleteOutdoorActivityKeys.lists(),
    });
  });

  it('shows an error toast when the POST fails', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ errors: [{ detail: 'Journal not found' }] }),
    } as Response);

    const { result } = renderHook(
      () => useUndismissIncompleteOutdoorActivity(),
      { wrapper: harness.wrapper }
    );

    result.current.mutate('7');

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).toHaveBeenCalledWith('Journal not found');
  });
});
