/**
 * @jest-environment jsdom
 */

/**
 * Journal and contact mutations must refresh the task caches.
 *
 * A task's read shapes **embed** the entities they reference rather than
 * pointing at them: `due_journal.title`, `due_journal.date`,
 * `due_journal.cancelled`, the derived `lapsed`/`lapse_reason`, and each
 * contact's `display_name` and `photo_url` all arrive inside the task payload.
 * So a journal or contact write changes what a *task* query would answer, and
 * with the app-wide five-minute `staleTime` nothing would refetch it.
 *
 * The consequence is not cosmetic. Moving a journal's date into the past, or
 * cancelling it, is what **lapses** the tasks due in it — and the journal's own
 * detail view is showing those very tasks. Without this refresh the user edits
 * the date and the task section below keeps claiming the task is fine.
 *
 * `taskKeys.all` rather than a narrower namespace because all three sibling
 * namespaces — `detail`, `journalList` and `upcoming` — carry the same embedded
 * refs, so all three are genuinely reachable. That is the rule in
 * `frontend-design.md`: a mutation names the namespaces its change can reach.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { ReactNode } from 'react';
import { taskKeys } from '../tasks';
import { useUpdateJournal, useUpdateJournalField } from '../journals';
import {
  useDeleteContact,
  useUpdateContact,
  useUpdateContactField,
} from '../contacts';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// `jest.setup.ts` mocks `@/lib/constants` down to the handful of endpoints the
// auth tests need, which leaves `API_ENDPOINTS.JOURNALS` undefined and every
// mutation here failing before it reaches `fetch`. The real constants are what
// this suite wants anyway — it is asserting on cache behaviour, not on URLs.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

let queryClient: QueryClient;

const createWrapper = ({ children }: { children: ReactNode }) =>
  React.createElement(QueryClientProvider, { client: queryClient }, children);

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  jest.clearAllMocks();
  mockFetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ data: { type: 'x', id: '1', attributes: {} } }),
  } as Response);
});

/** Every query key an `invalidateQueries` spy was asked to invalidate. */
function invalidatedKeys(
  spy: jest.SpyInstance
): ReadonlyArray<readonly unknown[]> {
  return spy.mock.calls.map(
    call => (call[0] as { queryKey: readonly unknown[] }).queryKey
  );
}

/** Did the mutation name the task namespace at all? */
async function expectTasksRefreshed(spy: jest.SpyInstance) {
  await waitFor(
    () => {
      expect(invalidatedKeys(spy)).toContainEqual(taskKeys.all);
    },
    // The journal mutations still delay their refresh behind a 150ms timer.
    { timeout: 3000 }
  );
}

describe('journal mutations refresh the task caches', () => {
  it('useUpdateJournal names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateJournal(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ id: '1', data: { title: 'Moved to next week' } });

    await expectTasksRefreshed(spy);
  });

  it('useUpdateJournalField names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateJournalField(), {
      wrapper: createWrapper,
    });

    result.current.mutate({
      journalId: '1',
      fieldName: 'event_date_range',
      value: { start: '2020-01-01T00:00:00Z', end: '2020-01-02T00:00:00Z' },
    });

    await expectTasksRefreshed(spy);
  });
});

describe('contact mutations refresh the task caches', () => {
  it('useUpdateContact names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateContact(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ id: '1', data: { first_name: 'Renamed' } });

    await expectTasksRefreshed(spy);
  });

  it('useUpdateContactField names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateContactField(), {
      wrapper: createWrapper,
    });

    result.current.mutate({
      contactId: '1',
      fieldName: 'first_name',
      value: 'Renamed',
    });

    await expectTasksRefreshed(spy);
  });

  it('useDeleteContact names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteContact(), {
      wrapper: createWrapper,
    });

    result.current.mutate('1');

    await expectTasksRefreshed(spy);
  });
});

describe('the refresh reaches every namespace that embeds the entity', () => {
  it('names `all`, not just the journal listings', async () => {
    // `detail` and `upcoming` embed the same journal and contact refs as
    // `journalList` does, so narrowing this to `journalLists()` would leave a
    // single task read and the dashboard showing the old title or lapse state.
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateJournal(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ id: '1', data: { title: 'Renamed' } });

    await expectTasksRefreshed(spy);
    const keys = invalidatedKeys(spy);
    expect(keys).not.toContainEqual(taskKeys.journalLists());
    expect(keys).not.toContainEqual(taskKeys.upcoming());
  });
});
