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
import { taskHistoryKeys, taskKeys, useUpdateTask } from '../tasks';
import { taskListHistoryKeys, taskListKeys } from '../task-list-keys';
import { useUpdateTaskList } from '../task-lists';
import { useMoveTaskToList } from '../list-tasks';
import { TaskStatus } from '@/types/tasks';
import { mockApiResponse } from '@/test-utils';
import {
  useDeleteJournal,
  useMergeJournal,
  useUpdateJournal,
  useUpdateJournalField,
} from '../journals';
import {
  useDeleteContact,
  useMergeContact,
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
  mockFetch.mockResolvedValue(
    mockApiResponse({ data: { type: 'x', id: '1', attributes: {} } })
  );
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
    const { result } = renderHook(() => useUpdateJournal('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({ title: 'Moved to next week' });

    await expectTasksRefreshed(spy);
  });

  it('useUpdateJournalField names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateJournalField('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({
      fieldName: 'event_date_range',
      value: { start: '2020-01-01T00:00:00Z', end: '2020-01-02T00:00:00Z' },
    });

    await expectTasksRefreshed(spy);
  });

  it('useMergeJournal names the task namespace', async () => {
    // A merge re-points the absorbed journal's task links at the survivor, so
    // a listing cached before it would omit the tasks that moved.
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useMergeJournal(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ targetId: '1', sourceId: '2' });

    await expectTasksRefreshed(spy);
  });

  it('useDeleteJournal names the task namespace', async () => {
    // Deleting a journal that is only an intermediate link is permitted, and
    // it removes that link from every task that held it.
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteJournal(), {
      wrapper: createWrapper,
    });

    result.current.mutate('1');

    await expectTasksRefreshed(spy);
  });
});

describe('contact mutations refresh the task caches', () => {
  it('useUpdateContact names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateContact('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({ first_name: 'Renamed' });

    await expectTasksRefreshed(spy);
  });

  it('useUpdateContactField names the task namespace', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateContactField('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({
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

  it('useMergeContact names the task namespace', async () => {
    // The merge deletes the source contact, so any task row still holding its
    // embedded copy would keep showing a contact that no longer exists.
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useMergeContact(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ survivorId: '1', sourceId: '2' });

    await expectTasksRefreshed(spy);
  });
});

describe('the refresh reaches every namespace that embeds the entity', () => {
  it('names `all`, not just the journal listings', async () => {
    // `detail` and `upcoming` embed the same journal and contact refs as
    // `journalList` does, so narrowing this to `journalLists()` would leave a
    // single task read and the dashboard showing the old title or lapse state.
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateJournal('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({ title: 'Renamed' });

    await expectTasksRefreshed(spy);
    const keys = invalidatedKeys(spy);
    expect(keys).not.toContainEqual(taskKeys.journalLists());
    expect(keys).not.toContainEqual(taskKeys.upcoming());
  });
});

describe('a task history cache is not collateral damage', () => {
  it('a journal mutation does not discard it', async () => {
    // A journal write changes what a *task* answers — its title, its date, its
    // lapse — so it invalidates `taskKeys.all`. It cannot change what already
    // *happened* to a task, so it must not reach the history. That is only
    // true because history lives under a root of its own; nested under
    // `taskKeys.all` it would be thrown away by every mutation above.
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateJournal('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({ title: 'Renamed' });

    await expectTasksRefreshed(spy);
    for (const key of invalidatedKeys(spy)) {
      expect(key[0]).not.toBe(taskHistoryKeys.all[0]);
    }
  });

  it('a contact mutation does not discard it either', async () => {
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateContact('1'), {
      wrapper: createWrapper,
    });

    result.current.mutate({ first_name: 'Renamed' });

    await expectTasksRefreshed(spy);
    for (const key of invalidatedKeys(spy)) {
      expect(key[0]).not.toBe(taskHistoryKeys.all[0]);
    }
  });

  it('the history root is outside the task namespace', async () => {
    // Stated directly as well as observed through the mutations, because this
    // is the property every case above depends on and a future rename could
    // move it back under `tasks` without failing any of them.
    expect(taskHistoryKeys.all[0]).not.toBe(taskKeys.all[0]);
    expect(taskHistoryKeys.list('1').slice(0, taskKeys.all.length)).not.toEqual(
      [...taskKeys.all]
    );
  });
});

describe('a task write refreshes the history the user is looking at', () => {
  it('invalidates the key a mounted disclosure actually holds', async () => {
    // The point of this test is that an exact-key assertion cannot make it.
    // A query-key filter matches by deep-partial equality, so the tempting
    // `taskHistoryKeys.list(taskId)` — which carries
    // `{ page: undefined, limit: undefined }` — matches no mounted query and
    // invalidates nothing, while a test comparing invalidated keys to that same
    // value passes. So this seeds the key the journal row's feed really uses
    // and asks the cache whether it was reached.
    const mountedKey = taskHistoryKeys.list('1', 1, 5);
    queryClient.setQueryData(mountedKey, { data: [], meta: undefined });
    expect(queryClient.getQueryState(mountedKey)?.isInvalidated).toBe(false);

    const { result } = renderHook(() => useUpdateTask(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ taskId: '1', status: TaskStatus.DONE });

    await waitFor(() => {
      expect(queryClient.getQueryState(mountedKey)?.isInvalidated).toBe(true);
    });
  });

  it('leaves another task’s history alone', async () => {
    const other = taskHistoryKeys.list('2', 1, 5);
    queryClient.setQueryData(other, { data: [], meta: undefined });

    const { result } = renderHook(() => useUpdateTask(), {
      wrapper: createWrapper,
    });

    result.current.mutate({ taskId: '1', status: TaskStatus.DONE });

    await waitFor(() => {
      expect(
        queryClient.getQueryState(taskHistoryKeys.list('1', 1, 5))
      ).toBeUndefined();
    });
    expect(queryClient.getQueryState(other)?.isInvalidated).toBe(false);
  });
});

/**
 * Lists and tasks, across their two roots.
 *
 * A list is not a task resource, so it has a root of its own and a task write
 * must neither cancel nor patch it — but a task write *does* move a list's
 * `open_task_count`, and a list write *does* change the `task_list` every task
 * read embeds. Those two dependencies are named explicitly by the mutations,
 * and these tests ask the cache whether each was reached.
 */
describe('lists and tasks refresh each other across their roots', () => {
  const activeListing = taskListKeys.listing({ archived: 'active' });

  /** A list whose id is the same as task 1's, as ids are per table. */
  const listingWithListOne = {
    data: [
      {
        type: 'task-lists',
        id: '1',
        attributes: { name: 'Packing', open_task_count: 2 },
      },
    ],
  };

  it('keeps lists and their history outside the task namespace', () => {
    expect(taskListKeys.all[0]).not.toBe(taskKeys.all[0]);
    expect(taskListHistoryKeys.all[0]).not.toBe(taskKeys.all[0]);
  });

  it('keeps the list-task namespace a sibling of the others, both ways', async () => {
    const keys = {
      detail: taskKeys.detail('1'),
      journal: taskKeys.journalList('7'),
      upcoming: taskKeys.upcomingWindow(7),
      onList: taskKeys.openOnList('3'),
    };
    Object.values(keys).forEach(key =>
      queryClient.setQueryData(key, { data: [] })
    );

    await queryClient.invalidateQueries({ queryKey: taskKeys.onLists() });
    expect(queryClient.getQueryState(keys.onList)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(keys.detail)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(keys.journal)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(keys.upcoming)?.isInvalidated).toBe(false);

    queryClient.setQueryData(keys.onList, { data: [] });
    await queryClient.invalidateQueries({ queryKey: taskKeys.journalLists() });
    await queryClient.invalidateQueries({ queryKey: taskKeys.upcoming() });
    await queryClient.invalidateQueries({ queryKey: taskKeys.details() });
    expect(queryClient.getQueryState(keys.onList)?.isInvalidated).toBe(false);
  });

  it('a status tick neither patches nor cancels the lists, though it moves their counts', async () => {
    queryClient.setQueryData(activeListing, listingWithListOne);
    const cancelSpy = jest.spyOn(queryClient, 'cancelQueries');

    const { result } = renderHook(() => useUpdateTask(), {
      wrapper: createWrapper,
    });
    result.current.mutate({ taskId: '1', status: TaskStatus.DONE });

    // The open count moved, so the listing is re-read...
    await waitFor(() => {
      expect(queryClient.getQueryState(activeListing)?.isInvalidated).toBe(
        true
      );
    });
    // ...but the optimistic patch, which matches task ids, never touched list 1.
    expect(queryClient.getQueryData(activeListing)).toEqual(listingWithListOne);
    // And the only cancel that reached the lists is the one that precedes
    // their refresh, never the optimistic one over `taskKeys.all`.
    const optimisticCancel = cancelSpy.mock.calls[0][0] as {
      queryKey: readonly unknown[];
    };
    expect(optimisticCancel.queryKey).toEqual(taskKeys.all);
  });

  it('a task write refreshes the tasks shown on a list', async () => {
    const onList = taskKeys.openOnList('3');
    queryClient.setQueryData(onList, { data: [], meta: { total: 0 } });

    const { result } = renderHook(() => useUpdateTask(), {
      wrapper: createWrapper,
    });
    result.current.mutate({ taskId: '1', text: 'Pack the tent' });

    await waitFor(() => {
      expect(queryClient.getQueryState(onList)?.isInvalidated).toBe(true);
    });
  });

  it('a list rename refreshes a task read that embeds the list, and the list history', async () => {
    const detail = taskKeys.detail('5');
    const history = taskListHistoryKeys.list('3', 1, 5);
    queryClient.setQueryData(detail, { data: { id: '5', attributes: {} } });
    queryClient.setQueryData(history, { data: [] });
    mockFetch.mockResolvedValue(
      mockApiResponse({
        data: { type: 'task-lists', id: '3', attributes: { name: 'Trip' } },
      })
    );

    const { result } = renderHook(() => useUpdateTaskList(), {
      wrapper: createWrapper,
    });
    result.current.mutate({ listId: '3', name: 'Trip' });

    await waitFor(() => {
      expect(queryClient.getQueryState(detail)?.isInvalidated).toBe(true);
    });
    expect(queryClient.getQueryState(history)?.isInvalidated).toBe(true);
  });
});

describe("a list's tasks refresh with the task data they embed", () => {
  it('a journal write reaches the tasks shown on a list', async () => {
    // A list task due in that journal embeds its title and date.
    const onList = taskKeys.openOnList('3');
    queryClient.setQueryData(onList, { data: [], meta: { total: 0 } });

    const { result } = renderHook(() => useUpdateJournal('1'), {
      wrapper: createWrapper,
    });
    result.current.mutate({ title: 'Moved to next week' });

    await waitFor(
      () => {
        expect(queryClient.getQueryState(onList)?.isInvalidated).toBe(true);
      },
      { timeout: 3000 }
    );
  });

  it('moving a task refreshes the list it left and the list it joined', async () => {
    const left = taskKeys.openOnList('3');
    const joined = taskKeys.openOnList('5');
    queryClient.setQueryData(left, { data: [], meta: { total: 0 } });
    queryClient.setQueryData(joined, { data: [], meta: { total: 0 } });

    const { result } = renderHook(() => useMoveTaskToList(), {
      wrapper: createWrapper,
    });
    result.current.mutate({ taskId: '1', taskListId: '5' });

    await waitFor(() => {
      expect(queryClient.getQueryState(left)?.isInvalidated).toBe(true);
    });
    expect(queryClient.getQueryState(joined)?.isInvalidated).toBe(true);
  });
});
