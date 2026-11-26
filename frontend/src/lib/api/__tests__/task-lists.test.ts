/**
 * @jest-environment jsdom
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import {
  TASK_LIST_ARCHIVED,
  TASK_LIST_CHANGED,
  useArchiveTaskList,
  useCreateTaskList,
  useDeleteTaskList,
  useMoveTaskList,
  useTaskList,
  useTaskListHistory,
  useTaskLists,
  useUnarchiveTaskList,
  useUpdateTaskList,
} from '../task-lists';
import { taskListHistoryKeys, taskListKeys } from '../task-list-keys';
import { TaskApiError, taskHistoryKeys, taskKeys } from '../tasks';
import { historyKeys } from '../contacts';
import { homeDashboardKeys } from '../home-dashboard';
import { journalKeys } from '../journal-keys';
import { createQueryTestHarness, mockApiResponse } from '@/test-utils';
import type {
  TaskListResource,
  TaskListResponse,
  TaskListsResponse,
  TaskListSummaryResource,
} from '@/types/task-lists';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// The global setup mocks `@/lib/constants` down to the auth endpoints; this
// suite asserts on the real URLs.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

function list(
  id: string,
  name: string,
  attributes: Partial<TaskListResource['attributes']> = {}
): TaskListResource {
  return {
    type: 'task-lists',
    id,
    attributes: {
      name,
      icon: null,
      position: Number(id),
      archived: false,
      archived_at: null,
      created_at: '2026-11-20T00:00:00Z',
      updated_at: '2026-11-20T00:00:00Z',
      ...attributes,
    },
    links: { self: `/api/task-lists/${id}` },
  };
}

function summary(
  id: string,
  name: string,
  openTaskCount: number
): TaskListSummaryResource {
  const { attributes, ...rest } = list(id, name);
  return {
    ...rest,
    attributes: { ...attributes, open_task_count: openTaskCount },
  };
}

function listing(...lists: TaskListSummaryResource[]): TaskListsResponse {
  return { data: lists };
}

function one(resource: TaskListResource): TaskListResponse {
  return { data: resource };
}

function apiError(status: number, code: string, detail: string): Response {
  return mockApiResponse(
    { errors: [{ status: String(status), code, detail }] },
    { status }
  );
}

/** A 204: no body, so the client must not parse one. */
function noContent(): Response {
  return {
    ok: true,
    status: 204,
    headers: { get: () => null },
    json: jest.fn().mockRejectedValue(new SyntaxError('Unexpected end')),
  } as unknown as Response;
}

/** A held-open request, and the function that finally answers it. */
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

const activeKey = taskListKeys.listing({ archived: 'active' });

/** Ids of the active listing, as cached. */
function cachedOrder(queryClient: ReturnType<typeof setup>['queryClient']) {
  return queryClient
    .getQueryData<TaskListsResponse>(activeKey)
    ?.data.map(entry => entry.id);
}

function setup() {
  return createQueryTestHarness();
}

beforeEach(() => {
  jest.clearAllMocks();
  mockFetch.mockReset();
});

describe('taskListKeys', () => {
  it('roots lists and their history apart from the task namespaces', () => {
    expect(taskListKeys.all).toEqual(['task-lists']);
    expect(taskListKeys.listing({ archived: 'archived' })).toEqual([
      'task-lists',
      'listing',
      { archived: 'archived' },
    ]);
    expect(taskListKeys.detail('3')).toEqual(['task-lists', 'detail', '3']);
    expect(taskListHistoryKeys.forList('3')).toEqual([
      'task-list-history',
      '3',
    ]);
    expect(taskListKeys.all[0]).not.toBe(taskKeys.all[0]);
    expect(taskListHistoryKeys.all[0]).not.toBe(taskHistoryKeys.all[0]);
  });
});

describe('reads', () => {
  it('lists the active lists by default', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValueOnce(
      mockApiResponse(listing(summary('1', 'Packing', 2)))
    );

    const { result } = renderHook(() => useTaskLists(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe('/api/task-lists?archived=active');
    expect(lastRequest().init.credentials).toBe('include');
    expect(result.current.data?.data[0].attributes.open_task_count).toBe(2);
  });

  it('asks for archived lists, or all of them, by name', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValue(mockApiResponse(listing()));

    const archived = renderHook(() => useTaskLists({ archived: 'archived' }), {
      wrapper,
    });
    await waitFor(() => expect(archived.result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe('/api/task-lists?archived=archived');

    const all = renderHook(() => useTaskLists({ archived: 'all' }), {
      wrapper,
    });
    await waitFor(() => expect(all.result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe('/api/task-lists?archived=all');
  });

  it('reads one list, and nothing without an id', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValueOnce(mockApiResponse(one(list('3', 'Trip'))));

    const { result } = renderHook(() => useTaskList('3'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe('/api/task-lists/3');

    renderHook(() => useTaskList(''), { wrapper });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("reads a list's history a page at a time", async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValueOnce(mockApiResponse({ data: [] }));

    const { result } = renderHook(
      () => useTaskListHistory('3', { page: 2, limit: 5 }),
      { wrapper }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastRequest().url).toBe('/api/task-lists/3/history?page=2&limit=5');
  });

  it('reports a refused read with its code', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValueOnce(
      apiError(404, 'TASK_LIST_NOT_FOUND', 'Task list not found')
    );

    const { result } = renderHook(() => useTaskList('9'), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(TaskApiError);
    expect((result.current.error as TaskApiError).code).toBe(
      'TASK_LIST_NOT_FOUND'
    );
  });
});

describe('useCreateTaskList', () => {
  it('sends the name, and an icon only when one was chosen', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValue(
      mockApiResponse(one(list('4', 'Packing')), { status: 201 })
    );

    const { result } = renderHook(() => useCreateTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ name: 'Packing' }));

    expect(lastRequest().url).toBe('/api/task-lists');
    expect(lastRequest().init.method).toBe('POST');
    expect(lastBody()).toEqual({
      data: { type: 'task-lists', attributes: { name: 'Packing' } },
    });

    await act(() =>
      result.current.mutateAsync({ name: 'Packing', icon: 'luggage' })
    );
    expect(lastBody()).toEqual({
      data: {
        type: 'task-lists',
        attributes: { name: 'Packing', icon: 'luggage' },
      },
    });

    expect(queryClient.getQueryData(taskListKeys.detail('4'))).toEqual(
      one(list('4', 'Packing'))
    );
    expect(invalidatedKeys(spy)).toContainEqual(taskListKeys.listings());
    expect(toast.success).toHaveBeenCalledWith('List created');
  });

  it('toasts a refusal and does not retry it', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValue(
      apiError(400, 'TASK_VALIDATION_ERROR', 'A list needs a name')
    );

    const { result } = renderHook(() => useCreateTaskList(), { wrapper });
    await act(async () => {
      await expect(result.current.mutateAsync({ name: ' ' })).rejects.toThrow(
        'A list needs a name'
      );
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith('A list needs a name');
  });
});

describe('useUpdateTaskList', () => {
  it('sends the id and only what changed; a null icon clears it', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValue(mockApiResponse(one(list('3', 'Trip'))));

    const { result } = renderHook(() => useUpdateTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '3', icon: null }));

    expect(lastRequest().url).toBe('/api/task-lists/3');
    expect(lastRequest().init.method).toBe('PATCH');
    expect(lastBody()).toEqual({
      data: { type: 'task-lists', id: '3', attributes: { icon: null } },
    });

    await act(() => result.current.mutateAsync({ listId: '3', name: 'Trip' }));
    expect(lastBody()).toEqual({
      data: { type: 'task-lists', id: '3', attributes: { name: 'Trip' } },
    });
  });

  it('stores the list and refreshes everything that embeds it', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValue(mockApiResponse(one(list('3', 'Trip'))));

    const { result } = renderHook(() => useUpdateTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '3', name: 'Trip' }));

    expect(queryClient.getQueryData(taskListKeys.detail('3'))).toEqual(
      one(list('3', 'Trip'))
    );
    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining([
        taskListKeys.listings(),
        taskKeys.all,
        homeDashboardKeys.all,
        historyKeys.all,
        taskListHistoryKeys.forList('3'),
      ])
    );
    expect(toast.success).toHaveBeenCalledWith('List updated');
  });

  it('carries the archived refusal on the error for the caller', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValue(
      apiError(409, TASK_LIST_ARCHIVED, 'Unarchive the list first')
    );

    const { result } = renderHook(() => useUpdateTaskList(), { wrapper });
    let error: unknown;
    await act(async () => {
      error = await result.current
        .mutateAsync({ listId: '3', name: 'Trip' })
        .catch((caught: unknown) => caught);
    });

    expect((error as TaskApiError).code).toBe(TASK_LIST_ARCHIVED);
    expect((error as TaskApiError).status).toBe(409);
  });
});

describe('a write answer and an older read of the same list', () => {
  type Wrapper = ReturnType<typeof setup>['wrapper'];

  /** Holds a detail read open, runs the write, then lets the old read land. */
  async function expectAnswerSurvivesOlderRead(
    write: (wrapper: Wrapper) => Promise<void>
  ) {
    const { queryClient, wrapper } = setup();
    const releaseRead = heldRequest(() =>
      mockApiResponse(one(list('3', 'Old name')))
    );
    const detail = renderHook(() => useTaskList('3'), { wrapper });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

    const answer = one(list('3', 'Trip', { archived: true }));
    mockFetch.mockResolvedValue(mockApiResponse(answer));
    await write(wrapper);

    act(() => releaseRead());
    await waitFor(() => expect(detail.result.current.data).toEqual(answer));
    expect(queryClient.getQueryData(taskListKeys.detail('3'))).toEqual(answer);
  }

  it('a rename answer is not overwritten by a read that started before it', async () => {
    await expectAnswerSurvivesOlderRead(async wrapper => {
      const { result } = renderHook(() => useUpdateTaskList(), { wrapper });
      await act(() =>
        result.current.mutateAsync({ listId: '3', name: 'Trip' })
      );
    });
  });

  it('an archive answer is not overwritten by a read that started before it', async () => {
    await expectAnswerSurvivesOlderRead(async wrapper => {
      const { result } = renderHook(() => useArchiveTaskList(), { wrapper });
      await act(() => result.current.mutateAsync('3'));
    });
  });
});

describe('overlapping writes to one list', () => {
  it("an older write's answer arriving last does not overwrite the newer one, and the list is re-read", async () => {
    // The rename commits before the archive, but its answer — still
    // `archived: false` — arrives after the archive's.
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    const releaseRename = heldRequest(() =>
      mockApiResponse(one(list('3', 'Trip')))
    );
    const releaseArchive = heldRequest(() =>
      mockApiResponse(
        one(
          list('3', 'Trip', {
            archived: true,
            archived_at: '2026-11-26T01:00:00Z',
          })
        )
      )
    );

    const rename = renderHook(() => useUpdateTaskList(), { wrapper });
    const archive = renderHook(() => useArchiveTaskList(), { wrapper });
    act(() => rename.result.current.mutate({ listId: '3', name: 'Trip' }));
    act(() => archive.result.current.mutate('3'));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    act(() => releaseArchive());
    await waitFor(() => expect(archive.result.current.isSuccess).toBe(true));
    act(() => releaseRename());
    await waitFor(() => expect(rename.result.current.isSuccess).toBe(true));

    expect(
      queryClient.getQueryData<TaskListResponse>(taskListKeys.detail('3'))?.data
        .attributes.archived
    ).toBe(true);
    await waitFor(() =>
      expect(invalidatedKeys(spy)).toContainEqual(taskListKeys.detail('3'))
    );
  });

  it("a write answering after the list's deletion does not bring the list back", async () => {
    // The rename commits before the delete, but its answer arrives after the
    // delete has removed the list's detail.
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(taskListKeys.detail('3'), one(list('3', 'Old')));
    const releaseRename = heldRequest(() =>
      mockApiResponse(one(list('3', 'Trip')))
    );
    mockFetch.mockResolvedValueOnce(noContent());

    const rename = renderHook(() => useUpdateTaskList(), { wrapper });
    const remove = renderHook(() => useDeleteTaskList(), { wrapper });
    act(() => rename.result.current.mutate({ listId: '3', name: 'Trip' }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    await act(() => remove.result.current.mutateAsync('3'));
    expect(queryClient.getQueryData(taskListKeys.detail('3'))).toBeUndefined();

    act(() => releaseRename());
    await waitFor(() => expect(rename.result.current.isSuccess).toBe(true));

    expect(queryClient.getQueryData(taskListKeys.detail('3'))).toBeUndefined();
  });

  it('a lone write stores its answer without a re-read of the list', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValue(mockApiResponse(one(list('3', 'Trip'))));

    const { result } = renderHook(() => useUpdateTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '3', name: 'Trip' }));

    expect(invalidatedKeys(spy)).not.toContainEqual(taskListKeys.detail('3'));
  });
});

describe('useArchiveTaskList and useUnarchiveTaskList', () => {
  it.each([
    ['archive', useArchiveTaskList, 'List archived'],
    ['unarchive', useUnarchiveTaskList, 'List unarchived'],
  ] as const)(
    'sends %s with no body and stores the answer as the list',
    async (action, useAction, wording) => {
      const { queryClient, wrapper } = setup();
      const spy = jest.spyOn(queryClient, 'invalidateQueries');
      const answer = one(
        list('3', 'Trip', {
          archived: action === 'archive',
          archived_at: action === 'archive' ? '2026-11-26T01:00:00Z' : null,
        })
      );
      queryClient.setQueryData(activeKey, listing(summary('3', 'Trip', 1)));
      mockFetch.mockResolvedValue(mockApiResponse(answer));

      const { result } = renderHook(() => useAction(), { wrapper });
      await act(() => result.current.mutateAsync('3'));

      expect(lastRequest().url).toBe(`/api/task-lists/3/${action}`);
      expect(lastRequest().init.method).toBe('POST');
      expect(lastRequest().init.body).toBeUndefined();
      expect(queryClient.getQueryData(taskListKeys.detail('3'))).toEqual(
        answer
      );
      // The answer is a list, not a listing entry: it carries no count, so
      // it is never written where the listing is cached.
      expect(
        queryClient.getQueryData<TaskListsResponse>(activeKey)?.data[0]
          .attributes.open_task_count
      ).toBe(1);
      expect(invalidatedKeys(spy)).toEqual(
        expect.arrayContaining([
          taskListKeys.listings(),
          taskKeys.all,
          homeDashboardKeys.all,
          historyKeys.all,
          taskListHistoryKeys.forList('3'),
        ])
      );
      expect(toast.success).toHaveBeenCalledWith(wording);
    }
  );
});

describe('useDeleteTaskList', () => {
  it('expects no content, forgets the list and its tasks, and refreshes the rest', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    queryClient.setQueryData(taskListKeys.detail('3'), one(list('3', 'Trip')));
    queryClient.setQueryData(taskKeys.openOnList('3'), {
      data: [],
      meta: { total: 0 },
    });
    mockFetch.mockResolvedValue(noContent());

    const { result } = renderHook(() => useDeleteTaskList(), { wrapper });
    await act(() => result.current.mutateAsync('3'));

    expect(lastRequest().url).toBe('/api/task-lists/3');
    expect(lastRequest().init.method).toBe('DELETE');
    // Removed, not invalidated: a refetch would only answer 404.
    expect(queryClient.getQueryState(taskListKeys.detail('3'))).toBeUndefined();
    expect(queryClient.getQueryState(taskKeys.openOnList('3'))).toBeUndefined();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(invalidatedKeys(spy)).toEqual(
      expect.arrayContaining([
        taskListKeys.listings(),
        taskKeys.all,
        taskHistoryKeys.all,
        journalKeys.lists(),
        homeDashboardKeys.all,
        historyKeys.all,
        // The list's history stays readable and ends in the deletion.
        taskListHistoryKeys.forList('3'),
      ])
    );
    expect(toast.success).toHaveBeenCalledWith('List deleted');
  });

  it('carries a concurrent-change refusal on the error', async () => {
    const { wrapper } = setup();
    mockFetch.mockResolvedValue(
      apiError(409, TASK_LIST_CHANGED, 'The list changed; try again')
    );

    const { result } = renderHook(() => useDeleteTaskList(), { wrapper });
    let error: unknown;
    await act(async () => {
      error = await result.current
        .mutateAsync('3')
        .catch((caught: unknown) => caught);
    });

    expect((error as TaskApiError).code).toBe(TASK_LIST_CHANGED);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});

describe('useMoveTaskList', () => {
  function seedActive(queryClient: ReturnType<typeof setup>['queryClient']) {
    queryClient.setQueryData(
      activeKey,
      listing(
        summary('1', 'Packing', 3),
        summary('2', 'Errands', 0),
        summary('3', 'Trip', 5)
      )
    );
  }

  function moveAnswer(...ids: string[]) {
    return mockApiResponse({
      data: ids.map((id, position) => list(id, `renamed ${id}`, { position })),
    });
  }

  it('sends the index among the active lists', async () => {
    const { queryClient, wrapper } = setup();
    seedActive(queryClient);
    mockFetch.mockResolvedValue(moveAnswer('2', '3', '1'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '1', index: 2 }));

    expect(lastRequest().url).toBe('/api/task-lists/1/move');
    expect(lastRequest().init.method).toBe('POST');
    expect(lastBody()).toEqual({
      data: { type: 'task-list-moves', attributes: { index: 2 } },
    });
  });

  it('moves the list at once, then takes the answer without a refetch', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seedActive(queryClient);
    const release = heldRequest(() => moveAnswer('2', '3', '1'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '1', index: 2 }));

    await waitFor(() =>
      expect(cachedOrder(queryClient)).toEqual(['2', '3', '1'])
    );

    act(() => release());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = queryClient.getQueryData<TaskListsResponse>(activeKey);
    expect(cached?.data.map(entry => entry.id)).toEqual(['2', '3', '1']);
    // The answer brings the order and the positions, and nothing else: a
    // rename that landed while it was out must not be undone by it, and it
    // carries no counts.
    expect(cached?.data[2].attributes.position).toBe(2);
    expect(cached?.data[2].attributes.name).toBe('Packing');
    expect(cached?.data[2].attributes.open_task_count).toBe(3);
    expect(invalidatedKeys(spy)).not.toContainEqual(activeKey);
    expect(invalidatedKeys(spy)).toContainEqual(
      taskListKeys.listing({ archived: 'all' })
    );
  });

  it('puts the order back when the move fails', async () => {
    const { queryClient, wrapper } = setup();
    seedActive(queryClient);
    mockFetch.mockResolvedValue(
      apiError(409, TASK_LIST_ARCHIVED, 'Unarchive the list first')
    );

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    await act(async () => {
      await result.current
        .mutateAsync({ listId: '1', index: 2 })
        .catch(() => undefined);
    });

    expect(cachedOrder(queryClient)).toEqual(['1', '2', '3']);
    expect(toast.error).toHaveBeenCalledWith('Unarchive the list first');
  });

  it('lets the newest of two quick moves decide the order', async () => {
    const { queryClient, wrapper } = setup();
    seedActive(queryClient);
    const releaseFirst = heldRequest(() => moveAnswer('2', '3', '1'));
    const releaseSecond = heldRequest(() => moveAnswer('3', '2', '1'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '1', index: 2 }));
    act(() => result.current.mutate({ listId: '3', index: 0 }));
    await waitFor(() =>
      expect(cachedOrder(queryClient)).toEqual(['3', '2', '1'])
    );

    // The first answer predates the second move, so it must not undo it.
    act(() => releaseFirst());
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(cachedOrder(queryClient)).toEqual(['3', '2', '1']);

    act(() => releaseSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: ['task-list-move'] })).toBe(
        0
      )
    );
    expect(cachedOrder(queryClient)).toEqual(['3', '2', '1']);
  });

  it('confirms the order with a re-read after overlapping moves', async () => {
    // The answers' arrival order says nothing about the order the server
    // applied the moves in, so even the newest answer may predate the other.
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seedActive(queryClient);
    const releaseFirst = heldRequest(() => moveAnswer('2', '3', '1'));
    const releaseSecond = heldRequest(() => moveAnswer('3', '2', '1'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '1', index: 2 }));
    act(() => result.current.mutate({ listId: '3', index: 0 }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    act(() => releaseFirst());
    act(() => releaseSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: ['task-list-move'] })).toBe(
        0
      )
    );

    expect(invalidatedKeys(spy)).toContainEqual(activeKey);
  });

  it("takes a lone move's answer without a re-read, and forgets an earlier overlap", async () => {
    const { queryClient, wrapper } = setup();
    seedActive(queryClient);
    const releaseFirst = heldRequest(() => moveAnswer('2', '3', '1'));
    const releaseSecond = heldRequest(() => moveAnswer('3', '2', '1'));
    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '1', index: 2 }));
    act(() => result.current.mutate({ listId: '3', index: 0 }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    act(() => releaseFirst());
    act(() => releaseSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: ['task-list-move'] })).toBe(
        0
      )
    );

    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValueOnce(moveAnswer('2', '3', '1'));
    await act(() => result.current.mutateAsync({ listId: '3', index: 1 }));

    expect(invalidatedKeys(spy)).not.toContainEqual(activeKey);
  });

  it('re-reads the listing when the answer names other lists than the cache', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seedActive(queryClient);
    // A list created in another tab is in the answer but not the cache.
    mockFetch.mockResolvedValue(moveAnswer('2', '3', '4', '1'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '1', index: 3 }));

    expect(invalidatedKeys(spy)).toContainEqual(activeKey);
  });

  it('re-reads the listing when two moves both fail, rather than trusting a snapshot', async () => {
    // The second move's snapshot already holds the first's unconfirmed order.
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seedActive(queryClient);
    const failFirst = heldRequest(() =>
      apiError(503, 'UNAVAILABLE', 'Offline')
    );
    const failSecond = heldRequest(() =>
      apiError(503, 'UNAVAILABLE', 'Offline')
    );

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '3', index: 0 }));
    act(() => result.current.mutate({ listId: '2', index: 0 }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    act(() => failFirst());
    act(() => failSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: ['task-list-move'] })).toBe(
        0
      )
    );

    expect(invalidatedKeys(spy)).toContainEqual(activeKey);
  });

  it('re-reads rather than restoring the original order over a move the server applied', async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seedActive(queryClient);
    const failFirst = heldRequest(() =>
      apiError(503, 'UNAVAILABLE', 'Offline')
    );
    const succeedSecond = heldRequest(() => moveAnswer('2', '1', '3'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '3', index: 0 }));
    act(() => result.current.mutate({ listId: '2', index: 0 }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    // The newer move lands while the older is still out, so it waits...
    act(() => succeedSecond());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: ['task-list-move'] })).toBe(
        1
      )
    );
    // ...and the older one failing must not put back the order from before
    // both, which would undo the move the server did apply.
    act(() => failFirst());
    await waitFor(() =>
      expect(queryClient.isMutating({ mutationKey: ['task-list-move'] })).toBe(
        0
      )
    );

    expect(cachedOrder(queryClient)).not.toEqual(['1', '2', '3']);
    expect(invalidatedKeys(spy)).toContainEqual(activeKey);
  });

  it('re-reads the listing when the move cancelled a refresh in flight', async () => {
    // A tick elsewhere invalidated the listing; its refetch is still out when
    // the drag cancels it, so the count it would bring must be read again.
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    mockFetch.mockResolvedValueOnce(
      mockApiResponse(
        listing(
          summary('1', 'Packing', 3),
          summary('2', 'Errands', 0),
          summary('3', 'Trip', 5)
        )
      )
    );
    const listingHook = renderHook(() => useTaskLists(), { wrapper });
    await waitFor(() =>
      expect(listingHook.result.current.isSuccess).toBe(true)
    );
    heldRequest(() => mockApiResponse(listing()));
    void queryClient.refetchQueries({ queryKey: activeKey });
    await waitFor(() =>
      expect(queryClient.getQueryState(activeKey)?.fetchStatus).toBe('fetching')
    );
    mockFetch.mockResolvedValueOnce(moveAnswer('2', '3', '1'));
    mockFetch.mockResolvedValue(
      mockApiResponse(listing(summary('2', 'Errands', 0)))
    );

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '1', index: 2 }));

    expect(invalidatedKeys(spy)).toContainEqual(activeKey);
  });

  it('an older listing read that lands after the answer does not snap the order back', async () => {
    // A tick elsewhere starts a re-read of the listing while the move is out;
    // the read captured the old order and comes back after the answer.
    const { queryClient, wrapper } = setup();
    mockFetch.mockResolvedValueOnce(
      mockApiResponse(
        listing(
          summary('1', 'Packing', 3),
          summary('2', 'Errands', 0),
          summary('3', 'Trip', 5)
        )
      )
    );
    const listingHook = renderHook(() => useTaskLists(), { wrapper });
    await waitFor(() =>
      expect(listingHook.result.current.isSuccess).toBe(true)
    );

    const releaseMove = heldRequest(() => moveAnswer('2', '3', '1'));
    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    act(() => result.current.mutate({ listId: '1', index: 2 }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    const releaseOldRead = heldRequest(() =>
      mockApiResponse(
        listing(
          summary('1', 'Packing', 3),
          summary('2', 'Errands', 0),
          summary('3', 'Trip', 5)
        )
      )
    );
    void queryClient.invalidateQueries({ queryKey: activeKey });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(3));
    // Whatever re-read follows the answer sees the server's new order.
    mockFetch.mockResolvedValue(
      mockApiResponse(
        listing(
          summary('2', 'Errands', 0),
          summary('3', 'Trip', 5),
          summary('1', 'Packing', 3)
        )
      )
    );

    act(() => releaseMove());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => releaseOldRead());

    await waitFor(() =>
      expect(queryClient.getQueryState(activeKey)?.fetchStatus).toBe('idle')
    );
    expect(cachedOrder(queryClient)).toEqual(['2', '3', '1']);
  });

  it("refreshes the lists' details, whose positions a move renumbers", async () => {
    const { queryClient, wrapper } = setup();
    const spy = jest.spyOn(queryClient, 'invalidateQueries');
    seedActive(queryClient);
    mockFetch.mockResolvedValue(moveAnswer('2', '3', '1'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    await act(() => result.current.mutateAsync({ listId: '1', index: 2 }));

    expect(invalidatedKeys(spy)).toContainEqual(taskListKeys.details());
  });

  it('does not retry', async () => {
    const { queryClient, wrapper } = setup();
    seedActive(queryClient);
    mockFetch.mockResolvedValue(apiError(500, 'INTERNAL', 'Broken'));

    const { result } = renderHook(() => useMoveTaskList(), { wrapper });
    await act(async () => {
      await result.current
        .mutateAsync({ listId: '1', index: 2 })
        .catch(() => undefined);
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
