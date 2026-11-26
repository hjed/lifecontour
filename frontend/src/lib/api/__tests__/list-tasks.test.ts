/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import {
  TASK_LIST_REMOVAL_NEEDS_JOURNALS,
  TASK_REORDER_KEY,
  useCreateListTask,
  useMoveTaskToList,
  useRemoveTaskFromList,
  useReorderListTask,
  useTaskListCompletedTasks,
  useTaskListOpenTasks,
} from '../list-tasks';
import { TASK_LIST_CHANGED } from '../task-lists';
import { taskListKeys } from '../task-list-keys';
import {
  TaskApiError,
  taskHistoryKeys,
  taskKeys,
  useDeleteTask,
  useLinkTaskContact,
  useTask,
  useUpdateTask,
} from '../tasks';
import { historyKeys } from '../contacts';
import { homeDashboardKeys } from '../home-dashboard';
import { journalKeys } from '../journal-keys';
import { createQueryTestHarness, mockApiResponse } from '@/test-utils';
import {
  TaskStatus,
  type CompletedListTasksResponse,
  type ListTasksResponse,
  type TaskReadResource,
  type TaskResource,
} from '@/types/tasks';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

type Harness = ReturnType<typeof createQueryTestHarness>;

/** A task on list 3 as a write answers with it: no journals, no `overdue`. */
function written(id: string, text = `task ${id}`): TaskResource {
  return {
    type: 'tasks',
    id,
    attributes: {
      text,
      status: TaskStatus.NOT_DONE,
      creating_journal_id: null,
      due_journal_id: null,
      intermediate_journal_ids: [],
      task_list_id: 3,
      due_date: null,
      flagged: false,
      icon: null,
    },
  };
}

/** The same task as a read answers with it, resolved. */
function read(
  id: string,
  attributes: Partial<TaskReadResource['attributes']> = {}
): TaskReadResource {
  return {
    ...written(id),
    attributes: {
      ...written(id).attributes,
      creating_journal: null,
      due_journal: null,
      intermediate_journals: [],
      task_list: { id: 3, name: 'Packing', icon: null, archived: false },
      contacts: [{ id: 9, display_name: 'Sam', photo_url: null }],
      lapsed: false,
      lapse_reason: null,
      overdue: false,
      ...attributes,
    },
  };
}

function openTasks(...ids: string[]): ListTasksResponse {
  return { data: ids.map(id => read(id)), meta: { total: ids.length } };
}

function completedPage(
  ids: string[],
  page: number,
  pageCount: number
): CompletedListTasksResponse {
  return {
    data: ids.map(id => read(id, { status: TaskStatus.DONE })),
    meta: {
      total_count: pageCount * 2,
      page_count: pageCount,
      current_page: page,
      per_page: 2,
    },
    // Absolute, and built from the backend's own host: never followed.
    links: { next: page < pageCount ? 'http://backend:8000/x' : undefined },
  };
}

function apiError(status: number, code: string, detail: string): Response {
  return mockApiResponse(
    { errors: [{ status: String(status), code, detail }] },
    { status }
  );
}

function heldRequest(answer: () => Response): () => void {
  let release: () => void = () => undefined;
  mockFetch.mockImplementationOnce(
    () =>
      new Promise<Response>(resolve => {
        release = () => resolve(answer());
      })
  );
  return () => release();
}

function lastRequest(): { url: string; init: RequestInit } {
  const [url, init] = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
  return { url: String(url), init: init ?? {} };
}

function lastBody(): unknown {
  const { body } = lastRequest().init;
  return body === undefined ? undefined : JSON.parse(body as string);
}

function invalidatedKeys(
  spy: jest.SpyInstance
): ReadonlyArray<readonly unknown[]> {
  return spy.mock.calls.map(
    call => (call[0] as { queryKey: readonly unknown[] }).queryKey
  );
}

const openKey = taskKeys.openOnList('3');

function cachedOpen(queryClient: Harness['queryClient']) {
  return queryClient.getQueryData<ListTasksResponse>(openKey)?.data;
}

const cachedIds = (queryClient: Harness['queryClient']) =>
  cachedOpen(queryClient)?.map(task => task.id);

beforeEach(() => {
  jest.clearAllMocks();
  mockFetch.mockReset();
});

describe('useTaskListOpenTasks', () => {
  it("reads a list's open tasks, with their count", async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValueOnce(mockApiResponse(openTasks('1', '2')));

    const { result } = renderHook(() => useTaskListOpenTasks('3'), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe('/api/task-lists/3/tasks');
    expect(lastRequest().init.credentials).toBe('include');
    expect(result.current.data?.meta.total).toBe(2);
  });

  it('reads nothing without a list', () => {
    const { wrapper } = createQueryTestHarness();
    renderHook(() => useTaskListOpenTasks(''), { wrapper });
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe('useTaskListCompletedTasks', () => {
  it('reads the first page, then the next while pages remain', async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch
      .mockResolvedValueOnce(mockApiResponse(completedPage(['5', '6'], 1, 2)))
      .mockResolvedValueOnce(mockApiResponse(completedPage(['7'], 2, 2)));

    const { result } = renderHook(() => useTaskListCompletedTasks('3'), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe(
      '/api/task-lists/3/tasks/completed?page=1&limit=20'
    );
    expect(result.current.hasNextPage).toBe(true);

    await act(() => result.current.fetchNextPage());
    // Paged by number from `meta`, never by the absolute `links.next`.
    expect(lastRequest().url).toBe(
      '/api/task-lists/3/tasks/completed?page=2&limit=20'
    );
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(result.current.data?.pages.flatMap(page => page.data)).toHaveLength(
      3
    );
  });

  it('has no next page on a single page, nor on a page past the end', async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValueOnce(
      mockApiResponse({
        data: [],
        meta: { total_count: 0, page_count: 0, current_page: 1, per_page: 5 },
        links: { next: null },
      })
    );

    const { result } = renderHook(
      () => useTaskListCompletedTasks('3', { limit: 5 }),
      { wrapper }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe(
      '/api/task-lists/3/tasks/completed?page=1&limit=5'
    );
    expect(result.current.hasNextPage).toBe(false);
  });
});

describe('useCreateListTask', () => {
  it('sends the text and the one date it was given, and no empty contacts', async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValue(
      mockApiResponse({ data: written('8') }, { status: 201 })
    );

    const { result } = renderHook(() => useCreateListTask(), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        listId: '3',
        text: 'Tent',
        due_date: '2026-12-01',
        contact_ids: [],
      })
    );

    expect(lastRequest().url).toBe('/api/task-lists/3/tasks');
    expect(lastRequest().init.method).toBe('POST');
    expect(lastBody()).toEqual({
      data: {
        type: 'tasks',
        attributes: { text: 'Tent', due_date: '2026-12-01' },
      },
    });

    await act(() =>
      result.current.mutateAsync({
        listId: '3',
        text: 'Stove',
        due_journal_id: 4,
        contact_ids: [9],
      })
    );
    expect(lastBody()).toEqual({
      data: {
        type: 'tasks',
        attributes: { text: 'Stove', due_journal_id: 4, contact_ids: [9] },
      },
    });
  });

  it("refreshes the list's tasks, its count and every surface a new task reaches", async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValue(
      mockApiResponse({ data: written('8') }, { status: 201 })
    );

    const { result } = renderHook(() => useCreateListTask(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '3', text: 'Tent' }));

    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining([
        taskKeys.onLists(),
        taskKeys.journalLists(),
        taskKeys.upcoming(),
        homeDashboardKeys.all,
        journalKeys.lists(),
        taskListKeys.listings(),
      ])
    );
    expect(toast.success).toHaveBeenCalledWith('Task created successfully');
  });

  it("refreshes the contacts' feeds when it links contacts, and only then", async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValue(
      mockApiResponse({ data: written('8') }, { status: 201 })
    );

    const { result } = renderHook(() => useCreateListTask(), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        listId: '3',
        text: 'Tent',
        contact_ids: [9],
      })
    );
    expect(invalidatedKeys(spy)).toContainEqual(historyKeys.all);

    spy.mockClear();
    await act(() => result.current.mutateAsync({ listId: '3', text: 'Stove' }));
    expect(invalidatedKeys(spy)).toContainEqual(taskKeys.onLists());
    expect(invalidatedKeys(spy)).not.toContainEqual(historyKeys.all);
  });

  it('a failed creation does not repay an owed refresh while a task write is still out', async () => {
    // A creation has no task id, so the pending count does not include it:
    // one task write still out means "not last", not "only me".
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const releaseUpdate = heldRequest(() =>
      mockApiResponse({ data: written('2') })
    );
    mockFetch.mockResolvedValueOnce(mockApiResponse({ data: written('1') }));
    mockFetch.mockResolvedValueOnce(
      apiError(400, 'TASK_VALIDATION_ERROR', 'Text is required')
    );

    const update = renderHook(() => useUpdateTask(), { wrapper });
    const move = renderHook(() => useMoveTaskToList(), { wrapper });
    const create = renderHook(() => useCreateListTask(), { wrapper });
    act(() =>
      update.result.current.mutate({ taskId: '2', status: TaskStatus.DONE })
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    // The move settles with the update still out, so it owes the refresh.
    await act(() =>
      move.result.current.mutateAsync({ taskId: '1', taskListId: '5' })
    );

    spy.mockClear();
    await act(async () => {
      await create.result.current
        .mutateAsync({ listId: '3', text: ' ' })
        .catch(() => undefined);
    });
    expect(invalidatedKeys(spy)).not.toContainEqual(taskListKeys.listings());

    // The update, last standing, refreshes the shared surfaces itself.
    act(() => releaseUpdate());
    await waitFor(() =>
      expect(invalidatedKeys(spy)).toContainEqual(taskListKeys.listings())
    );
  });

  it('carries a past due date refusal on the error, and does not retry', async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValue(
      apiError(400, 'TASK_DUE_DATE_IN_PAST', 'Pick today or later')
    );

    const { result } = renderHook(() => useCreateListTask(), { wrapper });
    let error: unknown;
    await act(async () => {
      error = await result.current
        .mutateAsync({ listId: '3', text: 'Tent', due_date: '2020-01-01' })
        .catch((caught: unknown) => caught);
    });

    expect((error as TaskApiError).code).toBe('TASK_DUE_DATE_IN_PAST');
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith('Pick today or later');
  });
});

describe('useReorderListTask', () => {
  function seed(queryClient: Harness['queryClient']) {
    queryClient.setQueryData(openKey, openTasks('1', '2', '3', '4'));
  }

  function reorderAnswer(...ids: string[]) {
    return mockApiResponse({ data: ids.map(id => written(id, 'stale text')) });
  }

  it('sends the anchor as a JSON integer, and null for the top', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    seed(queryClient);
    mockFetch.mockResolvedValue(reorderAnswer('2', '3', '1', '4'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ taskId: '1', listId: '3', afterTaskId: '3' })
    );

    expect(lastRequest().url).toBe('/api/tasks/1/reorder');
    expect(lastRequest().init.method).toBe('POST');
    expect(lastBody()).toEqual({
      data: { type: 'task-reorders', attributes: { after_task_id: 3 } },
    });

    mockFetch.mockResolvedValue(reorderAnswer('4', '2', '3', '1'));
    await act(() =>
      result.current.mutateAsync({
        taskId: '4',
        listId: '3',
        afterTaskId: null,
      })
    );
    expect(lastBody()).toEqual({
      data: { type: 'task-reorders', attributes: { after_task_id: null } },
    });
  });

  it('moves the row at once, then orders the read models by the answer', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    seed(queryClient);
    const release = heldRequest(() => reorderAnswer('2', '3', '1', '4'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '1', listId: '3', afterTaskId: '3' })
    );
    await waitFor(() =>
      expect(cachedIds(queryClient)).toEqual(['2', '3', '1', '4'])
    );

    act(() => release());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(cachedIds(queryClient)).toEqual(['2', '3', '1', '4']);
    // The answer is the write shape: its ids order the rows, its rows never
    // replace the read models, which keep their contacts and their text.
    const moved = cachedOpen(queryClient)?.[2];
    expect(moved?.attributes.contacts).toHaveLength(1);
    expect(moved?.attributes.text).toBe('task 1');
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('puts back only the order when it fails, keeping a status ticked meanwhile', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    seed(queryClient);
    const releaseReorder = heldRequest(() =>
      apiError(500, 'INTERNAL_ERROR', 'Something went wrong')
    );
    const releaseUpdate = heldRequest(() =>
      mockApiResponse({ data: written('2') })
    );

    const reorder = renderHook(() => useReorderListTask(), { wrapper });
    const update = renderHook(() => useUpdateTask(), { wrapper });
    act(() =>
      reorder.result.current.mutate({
        taskId: '1',
        listId: '3',
        afterTaskId: '3',
      })
    );
    await waitFor(() =>
      expect(cachedIds(queryClient)).toEqual(['2', '3', '1', '4'])
    );
    act(() =>
      update.result.current.mutate({ taskId: '2', status: TaskStatus.DONE })
    );
    await waitFor(() =>
      expect(cachedOpen(queryClient)?.[0].attributes.status).toBe(
        TaskStatus.DONE
      )
    );

    act(() => releaseReorder());
    await waitFor(() => expect(reorder.result.current.isError).toBe(true));

    expect(cachedIds(queryClient)).toEqual(['1', '2', '3', '4']);
    expect(
      cachedOpen(queryClient)?.find(task => task.id === '2')?.attributes.status
    ).toBe(TaskStatus.DONE);
    expect(toast.error).toHaveBeenCalledWith('Something went wrong');

    act(() => releaseUpdate());
    await waitFor(() => expect(update.result.current.isSuccess).toBe(true));
  });

  it('lets the newest of two quick reorders decide the order', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    seed(queryClient);
    const releaseFirst = heldRequest(() => reorderAnswer('2', '3', '1', '4'));
    const releaseSecond = heldRequest(() => reorderAnswer('4', '2', '3', '1'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '1', listId: '3', afterTaskId: '3' })
    );
    act(() =>
      result.current.mutate({ taskId: '4', listId: '3', afterTaskId: null })
    );
    await waitFor(() =>
      expect(cachedIds(queryClient)).toEqual(['4', '2', '3', '1'])
    );

    act(() => releaseFirst());
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(cachedIds(queryClient)).toEqual(['4', '2', '3', '1']);

    act(() => releaseSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: TASK_REORDER_KEY })).toBe(0)
    );
    expect(cachedIds(queryClient)).toEqual(['4', '2', '3', '1']);
  });

  it('re-reads the list, without a toast, when it changed while the move waited', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    mockFetch.mockResolvedValue(
      apiError(409, TASK_LIST_CHANGED, 'The list changed; try again')
    );

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    let error: unknown;
    await act(async () => {
      error = await result.current
        .mutateAsync({ taskId: '1', listId: '3', afterTaskId: '3' })
        .catch((caught: unknown) => caught);
    });

    expect((error as TaskApiError).code).toBe(TASK_LIST_CHANGED);
    expect(cachedIds(queryClient)).toEqual(['1', '2', '3', '4']);
    expect(invalidatedKeys(spy)).toContainEqual(openKey);
    expect(toast.error).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('re-reads the list when the answer names other tasks than the cache', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    mockFetch.mockResolvedValue(reorderAnswer('2', '3', '1', '4', '9'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ taskId: '1', listId: '3', afterTaskId: '3' })
    );

    expect(invalidatedKeys(spy)).toContainEqual(openKey);
    expect(cachedIds(queryClient)).toEqual(['2', '3', '1', '4']);
  });

  it('settles each list on its own: a pending reorder elsewhere does not hold back a re-read', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    queryClient.setQueryData(taskKeys.openOnList('4'), openTasks('7', '8'));
    const failHere = heldRequest(() => apiError(503, 'UNAVAILABLE', 'Offline'));
    heldRequest(() => reorderAnswer('8', '7'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '1', listId: '3', afterTaskId: '3' })
    );
    act(() =>
      result.current.mutate({ taskId: '8', listId: '4', afterTaskId: null })
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    act(() => failHere());
    await waitFor(() =>
      expect(invalidatedKeys(spy)).toContainEqual(taskKeys.openOnList('3'))
    );
    expect(cachedIds(queryClient)).toEqual(['1', '2', '3', '4']);
  });

  it('re-reads the list when two reorders both fail, rather than trusting a snapshot', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    const failFirst = heldRequest(() =>
      apiError(503, 'UNAVAILABLE', 'Offline')
    );
    const failSecond = heldRequest(() =>
      apiError(503, 'UNAVAILABLE', 'Offline')
    );

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '4', listId: '3', afterTaskId: null })
    );
    act(() =>
      result.current.mutate({ taskId: '3', listId: '3', afterTaskId: null })
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    act(() => failFirst());
    act(() => failSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: TASK_REORDER_KEY })).toBe(0)
    );

    expect(invalidatedKeys(spy)).toContainEqual(openKey);
  });

  it('re-reads rather than restoring the original order over a reorder the server applied', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    const failFirst = heldRequest(() =>
      apiError(503, 'UNAVAILABLE', 'Offline')
    );
    const succeedSecond = heldRequest(() => reorderAnswer('3', '1', '2', '4'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '4', listId: '3', afterTaskId: null })
    );
    act(() =>
      result.current.mutate({ taskId: '3', listId: '3', afterTaskId: null })
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    act(() => succeedSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: TASK_REORDER_KEY })).toBe(1)
    );
    act(() => failFirst());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: TASK_REORDER_KEY })).toBe(0)
    );

    expect(cachedIds(queryClient)).not.toEqual(['1', '2', '3', '4']);
    expect(invalidatedKeys(spy)).toContainEqual(openKey);
  });

  it('re-reads the list when the reorder cancelled a refresh in flight', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValueOnce(mockApiResponse(openTasks('1', '2', '3')));
    const open = renderHook(() => useTaskListOpenTasks('3'), { wrapper });
    await waitFor(() => expect(open.result.current.isSuccess).toBe(true));
    heldRequest(() => mockApiResponse(openTasks('1', '2', '3')));
    void queryClient.refetchQueries({ queryKey: openKey });
    await waitFor(() =>
      expect(queryClient.getQueryState(openKey)?.fetchStatus).toBe('fetching')
    );
    mockFetch.mockResolvedValueOnce(reorderAnswer('2', '1', '3'));
    mockFetch.mockResolvedValue(mockApiResponse(openTasks('2', '1', '3')));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ taskId: '1', listId: '3', afterTaskId: '2' })
    );

    expect(invalidatedKeys(spy)).toContainEqual(openKey);
  });

  it('an older read that lands after the answer does not snap the order back', async () => {
    // A text edit on another task starts a re-read of the list while the
    // reorder is out; the read captured the old order and lands afterwards.
    const { queryClient, wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValueOnce(mockApiResponse(openTasks('1', '2', '3')));
    const open = renderHook(() => useTaskListOpenTasks('3'), { wrapper });
    await waitFor(() => expect(open.result.current.isSuccess).toBe(true));

    const releaseReorder = heldRequest(() => reorderAnswer('2', '1', '3'));
    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '1', listId: '3', afterTaskId: '2' })
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    const releaseOldRead = heldRequest(() =>
      mockApiResponse(openTasks('1', '2', '3'))
    );
    void queryClient.invalidateQueries({ queryKey: openKey });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(3));
    mockFetch.mockResolvedValue(mockApiResponse(openTasks('2', '1', '3')));

    act(() => releaseReorder());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => releaseOldRead());

    await waitFor(() =>
      expect(queryClient.getQueryState(openKey)?.fetchStatus).toBe('idle')
    );
    expect(cachedIds(queryClient)).toEqual(['2', '1', '3']);
  });

  it('confirms the order with a re-read after overlapping reorders', async () => {
    // The answers' arrival order says nothing about the order the server
    // applied the reorders in, so even the newest answer may predate the other.
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    const releaseFirst = heldRequest(() => reorderAnswer('2', '3', '1', '4'));
    const releaseSecond = heldRequest(() => reorderAnswer('4', '2', '3', '1'));

    const { result } = renderHook(() => useReorderListTask(), { wrapper });
    act(() =>
      result.current.mutate({ taskId: '1', listId: '3', afterTaskId: '3' })
    );
    act(() =>
      result.current.mutate({ taskId: '4', listId: '3', afterTaskId: null })
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    act(() => releaseFirst());
    act(() => releaseSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: TASK_REORDER_KEY })).toBe(0)
    );

    expect(cachedIds(queryClient)).toEqual(['4', '2', '3', '1']);
    expect(invalidatedKeys(spy)).toContainEqual(openKey);
  });

  it('is not a task write, so a status change settling mid-drag still refreshes', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seed(queryClient);
    const releaseReorder = heldRequest(() => reorderAnswer('2', '3', '1', '4'));
    mockFetch.mockResolvedValueOnce(mockApiResponse({ data: written('2') }));

    const reorder = renderHook(() => useReorderListTask(), { wrapper });
    const update = renderHook(() => useUpdateTask(), { wrapper });
    act(() =>
      reorder.result.current.mutate({
        taskId: '1',
        listId: '3',
        afterTaskId: '3',
      })
    );
    await act(() =>
      update.result.current.mutateAsync({
        taskId: '2',
        status: TaskStatus.DONE,
      })
    );

    await waitFor(() =>
      expect(invalidatedKeys(spy)).toContainEqual(taskKeys.detail('2'))
    );

    act(() => releaseReorder());
    await waitFor(() => expect(reorder.result.current.isSuccess).toBe(true));
  });
});

describe('useMoveTaskToList', () => {
  it('sends the list as a JSON integer and refreshes both lists and their counts', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValue(mockApiResponse({ data: written('1') }));

    const { result } = renderHook(() => useMoveTaskToList(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ taskId: '1', taskListId: '5' })
    );

    expect(lastRequest().url).toBe('/api/tasks/1/move');
    expect(lastRequest().init.method).toBe('POST');
    expect(lastBody()).toEqual({
      data: { type: 'task-moves', attributes: { task_list_id: 5 } },
    });
    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining([
        taskKeys.detail('1'),
        taskKeys.onLists(),
        taskListKeys.listings(),
        homeDashboardKeys.all,
        historyKeys.all,
      ])
    );
    expect(toast.success).toHaveBeenCalledWith('Task moved to the list');
  });
  it("refreshes the moved task's own reads even while another task write is out", async () => {
    // The other write will refresh the shared listings when it settles, but
    // only for its own task: this task's detail and histories are this write's.
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const releaseUpdate = heldRequest(() =>
      mockApiResponse({ data: written('2') })
    );
    mockFetch.mockResolvedValueOnce(mockApiResponse({ data: written('1') }));

    const update = renderHook(() => useUpdateTask(), { wrapper });
    const move = renderHook(() => useMoveTaskToList(), { wrapper });
    act(() =>
      update.result.current.mutate({ taskId: '2', status: TaskStatus.DONE })
    );
    // The update cancels queries before it sends, so wait for its request.
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    await act(() =>
      move.result.current.mutateAsync({ taskId: '1', taskListId: '5' })
    );

    await waitFor(() =>
      expect(invalidatedKeys(spy)).toEqual(
        expect.arrayContaining([
          taskKeys.detail('1'),
          taskHistoryKeys.forTask('1'),
          historyKeys.all,
        ])
      )
    );

    act(() => releaseUpdate());
    await waitFor(() => expect(update.result.current.isSuccess).toBe(true));
  });

  it('the shared refresh it skipped still runs when the write it waited on fails', async () => {
    // The pending write is a contact link, which used to refresh only on
    // success: its failure would leave both lists showing the old membership.
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const failLink = heldRequest(() => apiError(503, 'UNAVAILABLE', 'Offline'));
    mockFetch.mockResolvedValueOnce(mockApiResponse({ data: written('1') }));

    const link = renderHook(() => useLinkTaskContact(), { wrapper });
    const move = renderHook(() => useMoveTaskToList(), { wrapper });
    act(() => link.result.current.mutate({ taskId: '2', contactId: '9' }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    await act(() =>
      move.result.current.mutateAsync({ taskId: '1', taskListId: '5' })
    );
    expect(invalidatedKeys(spy)).not.toContainEqual(taskListKeys.listings());

    act(() => failLink());
    await waitFor(() =>
      expect(invalidatedKeys(spy)).toContainEqual(taskListKeys.listings())
    );
    expect(invalidatedKeys(spy)).toContainEqual(taskKeys.onLists());
  });

  it('still refreshes when it fails after a status change settled behind it', async () => {
    // The status change skipped its own refresh because this move was out.
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const failMove = heldRequest(() => apiError(503, 'UNAVAILABLE', 'Offline'));
    mockFetch.mockResolvedValueOnce(mockApiResponse({ data: written('2') }));

    const move = renderHook(() => useMoveTaskToList(), { wrapper });
    const update = renderHook(() => useUpdateTask(), { wrapper });
    act(() => move.result.current.mutate({ taskId: '1', taskListId: '5' }));
    await act(() =>
      update.result.current.mutateAsync({
        taskId: '2',
        status: TaskStatus.DONE,
      })
    );
    expect(invalidatedKeys(spy)).not.toContainEqual(taskListKeys.listings());

    act(() => failMove());
    await waitFor(() =>
      expect(invalidatedKeys(spy)).toContainEqual(taskListKeys.listings())
    );
  });
});

describe('useRemoveTaskFromList', () => {
  it('sends no body, stores the read model it answers with, and returns it', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const answer = {
      data: read('1', {
        task_list_id: null,
        task_list: null,
        lapsed: true,
        lapse_reason: null,
      }),
    };
    mockFetch.mockResolvedValue(mockApiResponse(answer));

    const { result } = renderHook(() => useRemoveTaskFromList(), { wrapper });
    let returned: unknown;
    await act(async () => {
      returned = await result.current.mutateAsync('1');
    });

    expect(lastRequest().url).toBe('/api/tasks/1/remove-from-list');
    expect(lastRequest().init.method).toBe('POST');
    expect(lastRequest().init.body).toBeUndefined();
    expect(returned).toEqual(answer);
    expect(queryClient.getQueryData(taskKeys.detail('1'))).toEqual(answer);
    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining([
        taskKeys.onLists(),
        taskListKeys.listings(),
        historyKeys.all,
      ])
    );
  });

  it('is not overwritten by a read of the task that started before it', async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    const releaseRead = heldRequest(() => mockApiResponse({ data: read('1') }));
    const detail = renderHook(() => useTask('1'), { wrapper });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

    const answer = {
      data: read('1', { task_list_id: null, task_list: null, lapsed: true }),
    };
    mockFetch.mockResolvedValue(mockApiResponse(answer));
    const { result } = renderHook(() => useRemoveTaskFromList(), { wrapper });
    await act(() => result.current.mutateAsync('1'));

    act(() => releaseRead());
    await waitFor(() =>
      expect(detail.result.current.data?.data.attributes.task_list).toBeNull()
    );
    expect(
      queryClient.getQueryData<{ data: TaskReadResource }>(taskKeys.detail('1'))
        ?.data.attributes.lapsed
    ).toBe(true);
  });

  it("an answer arriving after the task's deletion does not bring the task back", async () => {
    const { queryClient, wrapper } = createQueryTestHarness();
    queryClient.setQueryData(taskKeys.detail('1'), { data: read('1') });
    const releaseRemove = heldRequest(() =>
      mockApiResponse({
        data: read('1', { task_list_id: null, task_list: null }),
      })
    );
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: { get: () => null },
      json: jest.fn().mockRejectedValue(new SyntaxError('Unexpected end')),
    } as unknown as Response);

    const remove = renderHook(() => useRemoveTaskFromList(), { wrapper });
    const destroy = renderHook(() => useDeleteTask(), { wrapper });
    act(() => remove.result.current.mutate('1'));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    await act(() => destroy.result.current.mutateAsync('1'));
    expect(queryClient.getQueryData(taskKeys.detail('1'))).toBeUndefined();

    act(() => releaseRemove());
    await waitFor(() => expect(remove.result.current.isSuccess).toBe(true));

    expect(queryClient.getQueryData(taskKeys.detail('1'))).toBeUndefined();
  });

  it('carries the refusal for a task without both journals', async () => {
    const { wrapper } = createQueryTestHarness();
    mockFetch.mockResolvedValue(
      apiError(409, TASK_LIST_REMOVAL_NEEDS_JOURNALS, 'Move or cancel it')
    );

    const { result } = renderHook(() => useRemoveTaskFromList(), { wrapper });
    let error: unknown;
    await act(async () => {
      error = await result.current
        .mutateAsync('1')
        .catch((caught: unknown) => caught);
    });

    expect((error as TaskApiError).code).toBe(TASK_LIST_REMOVAL_NEEDS_JOURNALS);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
