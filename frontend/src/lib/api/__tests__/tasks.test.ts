/**
 * @jest-environment jsdom
 */

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { readFileSync } from 'fs';
import { join } from 'path';
import React, { ReactNode } from 'react';
import {
  CONTACT_NOT_FOUND,
  TASK_DUE_JOURNAL_NOT_FUTURE,
  TASK_JOURNAL_IS_ANCHOR,
  TASK_VALIDATION_ERROR,
  TaskApiError,
  taskHistoryKeys,
  taskKeys,
  taskValidationField,
  useAttachTaskIntermediateJournal,
  useCreateTask,
  useDeleteTask,
  useDetachTaskIntermediateJournal,
  useJournalTasks,
  useLinkTaskContact,
  useRetargetTask,
  useTask,
  useUnlinkTaskContact,
  useUpdateTask,
} from '../tasks';
import {
  JournalTasksResponse,
  LapseReason,
  TaskLinkRole,
  TaskReadResponse,
  TaskResponse,
  TaskStatus,
} from '@/types/tasks';

globalThis.fetch = jest.fn();

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

jest.mock('@/lib/constants', () => ({
  API_ENDPOINTS: {
    TASKS: {
      BY_ID: (id: string) => `/api/tasks/${id}`,
      FOR_JOURNAL: (journalId: string) => `/api/journals/${journalId}/tasks`,
      RETARGET: (id: string) => `/api/tasks/${id}/retarget`,
      CONTACTS: (id: string) => `/api/tasks/${id}/relationships/contacts`,
      CONTACT: (id: string, contactId: string) =>
        `/api/tasks/${id}/relationships/contacts/${contactId}`,
      INTERMEDIATE_JOURNALS: (id: string) =>
        `/api/tasks/${id}/relationships/intermediate-journals`,
      INTERMEDIATE_JOURNAL: (id: string, journalId: string) =>
        `/api/tasks/${id}/relationships/intermediate-journals/${journalId}`,
    },
  },
  ERROR_MESSAGES: {
    FETCH_FAILED: 'Failed to fetch data. Please try again.',
    CREATE_FAILED: 'Failed to create item. Please try again.',
    UPDATE_FAILED: 'Failed to update item. Please try again.',
    DELETE_FAILED: 'Failed to delete item. Please try again.',
  },
  SUCCESS_MESSAGES: {
    TASK_CREATED: 'Task created successfully',
    TASK_UPDATED: 'Task updated successfully',
    TASK_DELETED: 'Task deleted successfully',
    TASK_RETARGETED: 'Task moved to its new due journal',
    TASK_CONTACT_LINKED: 'Contact linked successfully',
    TASK_CONTACT_UNLINKED: 'Contact unlinked successfully',
    TASK_JOURNAL_ATTACHED: 'Journal linked successfully',
    TASK_JOURNAL_DETACHED: 'Journal unlinked successfully',
  },
}));

const mockFetch = fetch as jest.MockedFunction<typeof fetch>;
const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

/** A JSON body the client can parse, with the status a real response carries. */
function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
  } as unknown as Response;
}

/** A JSON:API error body, as `create_domain_error_response` renders one. */
function errorResponse(status: number, code: string, detail: string): Response {
  return {
    ok: false,
    status,
    json: jest.fn().mockResolvedValue({
      errors: [{ status: String(status), code, detail }],
    }),
  } as unknown as Response;
}

const dueJournal = {
  id: 42,
  title: 'Team offsite',
  date: '2026-09-01',
  cancelled: false,
};

const creatingJournal = {
  id: 7,
  title: 'Monday standup',
  date: '2026-08-11',
  cancelled: false,
};

/** The read shape `GET /api/tasks/{id}` answers with. */
function taskReadResponse(
  overrides: Partial<TaskReadResponse['data']['attributes']> = {}
): TaskReadResponse {
  return {
    data: {
      type: 'tasks',
      id: '1',
      attributes: {
        text: 'Print the permit',
        status: TaskStatus.NOT_DONE,
        creating_journal_id: 7,
        due_journal_id: 42,
        intermediate_journal_ids: [],
        created_at: '2026-08-11T00:00:00Z',
        updated_at: '2026-08-11T00:00:00Z',
        creating_journal: creatingJournal,
        due_journal: dueJournal,
        intermediate_journals: [],
        contacts: [],
        lapsed: false,
        lapse_reason: null,
        ...overrides,
      },
      links: { self: '/api/tasks/1' },
    },
  };
}

/** The listing shape `GET /api/journals/{id}/tasks` answers with. */
function journalTasksResponse(): JournalTasksResponse {
  return {
    data: [
      {
        type: 'tasks',
        id: '1',
        attributes: {
          ...taskReadResponse().data.attributes,
          link_roles: [TaskLinkRole.DUE],
        },
        links: { self: '/api/tasks/1' },
      },
      {
        type: 'tasks',
        id: '2',
        attributes: {
          ...taskReadResponse().data.attributes,
          link_roles: [TaskLinkRole.CREATED, TaskLinkRole.MENTIONED],
        },
        links: { self: '/api/tasks/2' },
      },
    ],
    meta: {
      groups: { due: [1], created: [2], mentioned: [2] },
    },
  };
}

/** The write shape create, PATCH and retarget all answer with. */
function taskWriteResponse(
  overrides: Partial<TaskResponse['data']['attributes']> = {}
): TaskResponse {
  return {
    data: {
      type: 'tasks',
      id: '1',
      attributes: {
        text: 'Print the permit',
        status: TaskStatus.NOT_DONE,
        creating_journal_id: 7,
        due_journal_id: 42,
        intermediate_journal_ids: [],
        created_at: '2026-08-11T00:00:00Z',
        updated_at: '2026-08-11T00:00:00Z',
        ...overrides,
      },
      links: { self: '/api/tasks/1' },
    },
  };
}

/** A 204: no body at all, so the client must not try to parse one. */
function noContentResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: jest
      .fn()
      .mockRejectedValue(new SyntaxError('Unexpected end of JSON')),
  } as unknown as Response;
}

/** Enough of a jest spy to order its calls against another spy's. */
interface CallOrdered {
  mock: { invocationCallOrder: readonly number[] };
}

function firstCallOrder(spy: CallOrdered): number {
  return Math.min(...spy.mock.invocationCallOrder);
}

function lastCallOrder(spy: CallOrdered): number {
  return Math.max(...spy.mock.invocationCallOrder);
}

/** The key sets a spied `invalidateQueries` was asked to invalidate. */
function invalidatedKeys(
  spy: jest.SpyInstance
): ReadonlyArray<readonly unknown[]> {
  return spy.mock.calls.map(
    call => (call[0] as { queryKey: readonly unknown[] }).queryKey
  );
}

/** The single request body a spied `fetch` was called with. */
function requestBody(): unknown {
  const init = mockFetch.mock.calls[0][1] as RequestInit;
  return JSON.parse(init.body as string);
}

describe('Task API client', () => {
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
  });

  describe('taskKeys', () => {
    it('namespaces details, journal listings and the upcoming window under tasks', () => {
      expect(taskKeys.all).toEqual(['tasks']);
      expect(taskKeys.details()).toEqual(['tasks', 'detail']);
      expect(taskKeys.detail('1')).toEqual(['tasks', 'detail', '1']);
      expect(taskKeys.journalLists()).toEqual(['tasks', 'journal']);
      expect(taskKeys.journalList('7')).toEqual([
        'tasks',
        'journal',
        '7',
        null,
      ]);
      expect(taskKeys.journalList('7', TaskLinkRole.DUE)).toEqual([
        'tasks',
        'journal',
        '7',
        'due',
      ]);
      expect(taskKeys.upcoming()).toEqual(['tasks', 'upcoming']);
      expect(taskKeys.upcomingWindow(7)).toEqual(['tasks', 'upcoming', 7]);
    });

    it("invalidating a journal's task lists leaves the upcoming window alone", async () => {
      queryClient.setQueryData(
        taskKeys.journalList('7'),
        journalTasksResponse()
      );
      queryClient.setQueryData(taskKeys.upcomingWindow(7), []);

      await queryClient.invalidateQueries({
        queryKey: taskKeys.journalLists(),
      });

      expect(
        queryClient.getQueryState(taskKeys.journalList('7'))?.isInvalidated
      ).toBe(true);
      expect(
        queryClient.getQueryState(taskKeys.upcomingWindow(7))?.isInvalidated
      ).toBe(false);
    });

    it("invalidating the upcoming window leaves a journal's task lists alone", async () => {
      queryClient.setQueryData(
        taskKeys.journalList('7'),
        journalTasksResponse()
      );
      queryClient.setQueryData(taskKeys.upcomingWindow(7), []);

      await queryClient.invalidateQueries({ queryKey: taskKeys.upcoming() });

      expect(
        queryClient.getQueryState(taskKeys.upcomingWindow(7))?.isInvalidated
      ).toBe(true);
      expect(
        queryClient.getQueryState(taskKeys.journalList('7'))?.isInvalidated
      ).toBe(false);
    });
  });

  describe('useTask', () => {
    it('reads one task by its own id', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskReadResponse()));

      const { result } = renderHook(() => useTask('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/1', {
        credentials: 'include',
      });
    });

    it('surfaces the resolved journals, contacts and lapse the read model carries', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse(
          taskReadResponse({
            status: TaskStatus.NOT_DONE,
            lapsed: true,
            lapse_reason: LapseReason.DUE_JOURNAL_CANCELLED,
            due_journal: { ...dueJournal, cancelled: true },
            intermediate_journal_ids: [9],
            intermediate_journals: [
              {
                id: 9,
                title: 'Last week',
                date: '2026-08-04',
                cancelled: false,
              },
            ],
            contacts: [{ id: 3, display_name: 'Sarah', photo_url: null }],
          })
        )
      );

      const { result } = renderHook(() => useTask('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      const attributes = result.current.data!.data.attributes;
      expect(attributes.creating_journal.title).toBe('Monday standup');
      expect(attributes.due_journal.cancelled).toBe(true);
      expect(attributes.intermediate_journals).toHaveLength(1);
      expect(attributes.contacts[0].display_name).toBe('Sarah');
      expect(attributes.lapsed).toBe(true);
      expect(attributes.lapse_reason).toBe(LapseReason.DUE_JOURNAL_CANCELLED);
    });

    it('does not fetch without a task id', () => {
      renderHook(() => useTask(''), { wrapper: createWrapper });

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('throws a TaskApiError carrying the status and code of a failed read', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(404, 'TASK_NOT_FOUND', 'No task 99 of yours')
      );

      const { result } = renderHook(() => useTask('99'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      const error = result.current.error as TaskApiError;
      expect(error).toBeInstanceOf(TaskApiError);
      expect(error.status).toBe(404);
      expect(error.code).toBe('TASK_NOT_FOUND');
      expect(error.message).toBe('No task 99 of yours');
    });
  });

  describe('useJournalTasks', () => {
    it("lists a journal's tasks with their grouping", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(journalTasksResponse()));

      const { result } = renderHook(() => useJournalTasks('7'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(mockFetch).toHaveBeenCalledWith('/api/journals/7/tasks', {
        credentials: 'include',
      });
      expect(result.current.data!.meta.groups).toEqual({
        due: [1],
        created: [2],
        mentioned: [2],
      });
      expect(result.current.data!.data[1].attributes.link_roles).toEqual([
        TaskLinkRole.CREATED,
        TaskLinkRole.MENTIONED,
      ]);
    });

    it('sends the role filter when one is asked for', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(journalTasksResponse()));

      const { result } = renderHook(
        () => useJournalTasks('7', { role: TaskLinkRole.DUE }),
        { wrapper: createWrapper }
      );

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(mockFetch).toHaveBeenCalledWith('/api/journals/7/tasks?role=due', {
        credentials: 'include',
      });
    });

    it('caches a filtered listing separately from the unfiltered one', async () => {
      mockFetch.mockResolvedValue(jsonResponse(journalTasksResponse()));

      const { result: unfiltered } = renderHook(() => useJournalTasks('7'), {
        wrapper: createWrapper,
      });
      await waitFor(() => expect(unfiltered.current.isSuccess).toBe(true));

      const { result: filtered } = renderHook(
        () => useJournalTasks('7', { role: TaskLinkRole.DUE }),
        { wrapper: createWrapper }
      );
      await waitFor(() => expect(filtered.current.isSuccess).toBe(true));

      // Two requests, not one served from the other's cache entry: a filtered
      // listing narrows `link_roles` as well as the rows, so it is a different
      // answer rather than a subset.
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(mockFetch).toHaveBeenNthCalledWith(1, '/api/journals/7/tasks', {
        credentials: 'include',
      });
      expect(mockFetch).toHaveBeenNthCalledWith(
        2,
        '/api/journals/7/tasks?role=due',
        { credentials: 'include' }
      );
    });

    it('does not fetch without a journal id', () => {
      renderHook(() => useJournalTasks(''), { wrapper: createWrapper });

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('throws a TaskApiError when the journal is not yours', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(404, 'JOURNAL_NOT_FOUND', 'No journal 99 of yours')
      );

      const { result } = renderHook(() => useJournalTasks('99'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      const error = result.current.error as TaskApiError;
      expect(error.status).toBe(404);
      expect(error.code).toBe('JOURNAL_NOT_FOUND');
    });
  });

  describe('TaskApiError', () => {
    it('falls back to the generic fetch message when there is no error body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: jest.fn().mockRejectedValue(new SyntaxError('not JSON')),
      } as unknown as Response);

      const { result } = renderHook(() => useTask('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      const error = result.current.error as TaskApiError;
      expect(error.message).toBe('Failed to fetch data. Please try again.');
      expect(error.status).toBe(500);
      expect(error.code).toBeUndefined();
    });

    it('carries the machine-readable meta a refusal attaches', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: jest.fn().mockResolvedValue({
          errors: [
            {
              status: '400',
              code: 'TASK_DUE_JOURNAL_NOT_FUTURE',
              detail:
                'Journal 42 is dated 2026-08-01, which is not after today',
              meta: { journal_date: '2026-08-01', today: '2026-08-11' },
            },
          ],
        }),
      } as unknown as Response);

      const { result } = renderHook(() => useTask('1'), {
        wrapper: createWrapper,
      });

      await waitFor(() => expect(result.current.isError).toBe(true));

      const error = result.current.error as TaskApiError;
      expect(error.code).toBe('TASK_DUE_JOURNAL_NOT_FUTURE');
      expect(error.meta).toEqual({
        journal_date: '2026-08-01',
        today: '2026-08-11',
      });
    });
  });

  describe('useCreateTask', () => {
    it('posts to the creating journal with the due journal and contacts', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse(), 201));

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        journalId: '7',
        text: 'Print the permit',
        due_journal_id: 42,
        contact_ids: [3],
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/journals/7/tasks',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        })
      );
      expect(requestBody()).toEqual({
        data: {
          type: 'tasks',
          attributes: {
            text: 'Print the permit',
            due_journal_id: 42,
            contact_ids: [3],
          },
        },
      });
    });

    it('omits contact_ids entirely when none were chosen', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse(), 201));

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        journalId: '7',
        text: 'Print the permit',
        due_journal_id: 42,
      });

      expect(requestBody()).toEqual({
        data: {
          type: 'tasks',
          attributes: { text: 'Print the permit', due_journal_id: 42 },
        },
      });
    });

    it('treats an empty contact selection as no selection at all', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse(), 201));

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        journalId: '7',
        text: 'Print the permit',
        due_journal_id: 42,
        contact_ids: [],
      });

      // A picker that was opened and left empty means what an unopened one
      // means, so both send the same body rather than one sending `[]`.
      expect(requestBody()).toEqual({
        data: {
          type: 'tasks',
          attributes: { text: 'Print the permit', due_journal_id: 42 },
        },
      });
    });

    it('refreshes the journal listings and the upcoming window, but no task detail', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse(), 201));
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        journalId: '7',
        text: 'Print the permit',
        due_journal_id: 42,
      });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.journalLists(),
          taskKeys.upcoming(),
        ]);
      });
      expect(toast.success).toHaveBeenCalledWith('Task created successfully');
    });

    it('toasts the service refusal when the due journal is not future-dated', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(
          400,
          'TASK_DUE_JOURNAL_NOT_FUTURE',
          'Journal 42 is dated 2026-08-01, which is not after today'
        )
      );

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({
          journalId: '7',
          text: 'Print the permit',
          due_journal_id: 42,
        })
      ).rejects.toThrow(
        'Journal 42 is dated 2026-08-01, which is not after today'
      );

      expect(toast.error).toHaveBeenCalledWith(
        'Journal 42 is dated 2026-08-01, which is not after today'
      );
    });
  });

  describe('useUpdateTask', () => {
    it('sends only the status when only the status changed', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse(taskWriteResponse({ status: TaskStatus.DONE }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        taskId: '1',
        status: TaskStatus.DONE,
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tasks/1',
        expect.objectContaining({ method: 'PATCH' })
      );
      expect(requestBody()).toEqual({
        data: { type: 'tasks', id: '1', attributes: { status: 'done' } },
      });
    });

    it('sends only the text when only the text changed', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        taskId: '1',
        text: 'Return the book',
      });

      expect(requestBody()).toEqual({
        data: {
          type: 'tasks',
          id: '1',
          attributes: { text: 'Return the book' },
        },
      });
    });

    it('sends both when both changed, as one request', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        taskId: '1',
        text: 'Return the book',
        status: TaskStatus.CANCELLED,
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(requestBody()).toEqual({
        data: {
          type: 'tasks',
          id: '1',
          attributes: { text: 'Return the book', status: 'cancelled' },
        },
      });
    });

    it('refreshes the task, the journal listings, the upcoming window and its history', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        taskId: '1',
        status: TaskStatus.DONE,
      });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.detail('1'),
          taskKeys.journalLists(),
          taskKeys.upcoming(),
          taskHistoryKeys.forTask('1'),
        ]);
      });
      expect(toast.success).toHaveBeenCalledWith('Task marked done');
    });

    it('surfaces the refusal to move a cancelled task back with a PATCH', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(
          409,
          'TASK_STATUS_TRANSITION_REFUSED',
          'Retarget it onto a new future journal to reopen it'
        )
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ taskId: '1', status: TaskStatus.NOT_DONE })
      ).rejects.toMatchObject({ code: 'TASK_STATUS_TRANSITION_REFUSED' });

      expect(toast.error).toHaveBeenCalledWith(
        'Retarget it onto a new future journal to reopen it'
      );
    });
  });

  /**
   * The optimistic half of the inline status actions (ITER18-001 Phase 17).
   *
   * A row must read as done the instant it is ticked, and read as it did
   * before if the write fails — so the cache is patched in `onMutate` and
   * every snapshot restored in `onError`. These tests hold the request open
   * rather than resolving it, because a patch that only appears once the
   * response lands is not an optimistic one and would pass a naive assertion.
   */
  describe('useUpdateTask optimistic status change', () => {
    const listKey = taskKeys.journalList('7');

    /** A held-open `fetch`, plus the trigger that finally answers it. */
    function heldRequest(answer: () => Response): () => void {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(answer());
            };
          })
      );
      return () => {
        release();
      };
    }

    /** The status a cached journal listing is showing for one task. */
    function cachedListStatus(taskId: string): TaskStatus | undefined {
      return queryClient
        .getQueryData<JournalTasksResponse>(listKey)
        ?.data.find(task => task.id === taskId)?.attributes.status;
    }

    /** The status the cached single-task read is showing. */
    function cachedDetailStatus(): TaskStatus | undefined {
      return queryClient.getQueryData<TaskReadResponse>(taskKeys.detail('1'))
        ?.data.attributes.status;
    }

    function seedCache(listing = journalTasksResponse()): void {
      queryClient.setQueryData(listKey, listing);
      queryClient.setQueryData(taskKeys.detail('1'), taskReadResponse());
    }

    it('shows the new status in a cached journal listing before the response lands', async () => {
      seedCache();
      const release = heldRequest(() =>
        jsonResponse(taskWriteResponse({ status: TaskStatus.DONE }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      const settled = result.current.mutateAsync({
        taskId: '1',
        status: TaskStatus.DONE,
      });

      await waitFor(() => {
        expect(cachedListStatus('1')).toBe(TaskStatus.DONE);
      });

      release();
      await settled;
    });

    it('shows the new status in the cached single-task read before the response lands', async () => {
      seedCache();
      const release = heldRequest(() =>
        jsonResponse(taskWriteResponse({ status: TaskStatus.CANCELLED }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      const settled = result.current.mutateAsync({
        taskId: '1',
        status: TaskStatus.CANCELLED,
      });

      await waitFor(() => {
        expect(cachedDetailStatus()).toBe(TaskStatus.CANCELLED);
      });

      release();
      await settled;
    });

    it('leaves the listing’s other tasks alone', async () => {
      seedCache();
      mockFetch.mockResolvedValueOnce(
        jsonResponse(taskWriteResponse({ status: TaskStatus.DONE }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await result.current.mutateAsync({
        taskId: '1',
        status: TaskStatus.DONE,
      });

      expect(cachedListStatus('2')).toBe(TaskStatus.NOT_DONE);
    });

    /**
     * Lapse is *derived* from "still not done and the due journal is no longer
     * ahead of it", so a task that has just been marked done or cancelled
     * cannot be lapsed and its marker must go at once — otherwise ticking a
     * lapsed task off leaves it reading `Done · Lapsed` until the refetch.
     */
    it('clears the lapse marker when the task leaves not done', async () => {
      const lapsedListing = journalTasksResponse();
      lapsedListing.data[0].attributes.lapsed = true;
      lapsedListing.data[0].attributes.lapse_reason = LapseReason.DATE_PASSED;
      seedCache(lapsedListing);

      const release = heldRequest(() =>
        jsonResponse(taskWriteResponse({ status: TaskStatus.DONE }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      const settled = result.current.mutateAsync({
        taskId: '1',
        status: TaskStatus.DONE,
      });

      await waitFor(() => {
        const task = queryClient
          .getQueryData<JournalTasksResponse>(listKey)
          ?.data.find(entry => entry.id === '1');
        expect(task?.attributes.lapsed).toBe(false);
        expect(task?.attributes.lapse_reason).toBeNull();
      });

      release();
      await settled;
    });

    it('restores every cached namespace when the write fails', async () => {
      seedCache();
      mockFetch.mockResolvedValueOnce(
        errorResponse(500, 'INTERNAL_ERROR', 'Something went wrong')
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await expect(
        result.current.mutateAsync({ taskId: '1', status: TaskStatus.DONE })
      ).rejects.toThrow();

      await waitFor(() => {
        expect(cachedListStatus('1')).toBe(TaskStatus.NOT_DONE);
      });
      expect(cachedDetailStatus()).toBe(TaskStatus.NOT_DONE);
      expect(toast.error).toHaveBeenCalledWith('Something went wrong');
    });

    it('restores the lapse marker a failed completion had cleared', async () => {
      const lapsedListing = journalTasksResponse();
      lapsedListing.data[0].attributes.lapsed = true;
      lapsedListing.data[0].attributes.lapse_reason =
        LapseReason.DUE_JOURNAL_CANCELLED;
      seedCache(lapsedListing);

      mockFetch.mockResolvedValueOnce(
        errorResponse(500, 'INTERNAL_ERROR', 'Something went wrong')
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await expect(
        result.current.mutateAsync({ taskId: '1', status: TaskStatus.DONE })
      ).rejects.toThrow();

      await waitFor(() => {
        const task = queryClient
          .getQueryData<JournalTasksResponse>(listKey)
          ?.data.find(entry => entry.id === '1');
        expect(task?.attributes.lapsed).toBe(true);
        expect(task?.attributes.lapse_reason).toBe(
          LapseReason.DUE_JOURNAL_CANCELLED
        );
      });
    });

    it.each([
      [TaskStatus.DONE, 'Task marked done'],
      [TaskStatus.NOT_DONE, 'Task returned to not done'],
      [TaskStatus.CANCELLED, 'Task cancelled'],
    ])('announces %s as "%s"', async (status, expected) => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse(taskWriteResponse({ status }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await result.current.mutateAsync({ taskId: '1', status });

      expect(toast.success).toHaveBeenCalledWith(expected);
    });

    it('keeps the generic message for a text-only update', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await result.current.mutateAsync({
        taskId: '1',
        text: 'Return the book',
      });

      expect(toast.success).toHaveBeenCalledWith('Task updated successfully');
    });

    /**
     * Two rows in the same listing, ticked one after the other, and the first
     * fails.
     *
     * A rollback that restored whole cache *entries* would put back a snapshot
     * taken before the second task was patched, so a failure on one row would
     * silently undo another row the user had just ticked — and the user would
     * have no reason to connect the two. Restoring only the failed task's own
     * attributes is what keeps the two independent.
     */
    it('rolls back only the task that failed, not one patched beside it', async () => {
      seedCache();

      const releaseFirst = heldRequest(() =>
        errorResponse(500, 'INTERNAL_ERROR', 'Something went wrong')
      );
      const releaseSecond = heldRequest(() =>
        jsonResponse(taskWriteResponse({ status: TaskStatus.DONE }))
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });

      const first = result.current
        .mutateAsync({ taskId: '1', status: TaskStatus.DONE })
        .catch(() => undefined);
      await waitFor(() => {
        expect(cachedListStatus('1')).toBe(TaskStatus.DONE);
      });

      const second = result.current
        .mutateAsync({ taskId: '2', status: TaskStatus.CANCELLED })
        .catch(() => undefined);
      await waitFor(() => {
        expect(cachedListStatus('2')).toBe(TaskStatus.CANCELLED);
      });

      releaseFirst();
      await first;

      await waitFor(() => {
        expect(cachedListStatus('1')).toBe(TaskStatus.NOT_DONE);
      });
      expect(cachedListStatus('2')).toBe(TaskStatus.CANCELLED);

      releaseSecond();
      await second;
    });

    /**
     * The detail read and the journal listing are fetched independently and can
     * hold different values for the same task — one refetched a moment ago, the
     * other still inside the five-minute `staleTime`.
     *
     * A rollback that captured one entry's value and wrote it into all of them
     * would undo the *divergence* as well as the patch, replacing a fresher
     * cached value with a staler one from whichever entry happened to be
     * enumerated first. Each entry is restored to what **it** was showing.
     */
    it('restores each cached entry to its own previous value', async () => {
      const listing = journalTasksResponse();
      listing.data[0].attributes.status = TaskStatus.NOT_DONE;
      queryClient.setQueryData(listKey, listing);
      queryClient.setQueryData(
        taskKeys.detail('1'),
        taskReadResponse({ status: TaskStatus.DONE })
      );

      mockFetch.mockResolvedValueOnce(
        errorResponse(500, 'INTERNAL_ERROR', 'Something went wrong')
      );

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await expect(
        result.current.mutateAsync({
          taskId: '1',
          status: TaskStatus.CANCELLED,
        })
      ).rejects.toThrow();

      await waitFor(() => {
        expect(cachedListStatus('1')).toBe(TaskStatus.NOT_DONE);
      });
      expect(cachedDetailStatus()).toBe(TaskStatus.DONE);
    });

    it('leaves a cached status alone when only the text changed', async () => {
      seedCache();
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));

      const { result } = renderHook(() => useUpdateTask(), {
        wrapper: createWrapper,
      });
      await result.current.mutateAsync({
        taskId: '1',
        text: 'Return the book',
      });

      expect(cachedListStatus('1')).toBe(TaskStatus.NOT_DONE);
    });
  });

  describe('useRetargetTask', () => {
    it('posts the retarget operation with an explicit boolean acknowledgement', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse(
          taskWriteResponse({
            due_journal_id: 99,
            intermediate_journal_ids: [42],
          })
        )
      );

      const { result } = renderHook(() => useRetargetTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', due_journal_id: 99 });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tasks/1/retarget',
        expect.objectContaining({ method: 'POST' })
      );
      expect(requestBody()).toEqual({
        data: {
          type: 'task-retarget',
          attributes: { due_journal_id: 99, acknowledge_reopen: false },
        },
      });
    });

    it('sends the acknowledgement when reopening a done task was confirmed', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));

      const { result } = renderHook(() => useRetargetTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({
        taskId: '1',
        due_journal_id: 99,
        acknowledge_reopen: true,
      });

      expect(requestBody()).toEqual({
        data: {
          type: 'task-retarget',
          attributes: { due_journal_id: 99, acknowledge_reopen: true },
        },
      });
    });

    it('refreshes the task, the journal listings, the upcoming window and its history', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse(taskWriteResponse()));
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useRetargetTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', due_journal_id: 99 });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.detail('1'),
          taskKeys.journalLists(),
          taskKeys.upcoming(),
          taskHistoryKeys.forTask('1'),
        ]);
      });
      expect(toast.success).toHaveBeenCalledWith(
        'Task moved to its new due journal'
      );
    });

    it('raises no toast when a done task needs its reopen confirming', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(
          409,
          'TASK_REOPEN_NOT_ACKNOWLEDGED',
          'This task is done; confirm that reopening it is intended'
        )
      );

      const { result } = renderHook(() => useRetargetTask(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ taskId: '1', due_journal_id: 99 })
      ).rejects.toMatchObject({
        status: 409,
        code: 'TASK_REOPEN_NOT_ACKNOWLEDGED',
      });

      expect(toast.error).not.toHaveBeenCalled();
    });

    it('still toasts a retarget that failed for any other reason', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(
          400,
          'TASK_DUE_JOURNAL_NOT_FUTURE',
          'Journal 42 is dated 2026-08-01, which is not after today'
        )
      );

      const { result } = renderHook(() => useRetargetTask(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ taskId: '1', due_journal_id: 42 })
      ).rejects.toBeInstanceOf(TaskApiError);

      expect(toast.error).toHaveBeenCalledWith(
        'Journal 42 is dated 2026-08-01, which is not after today'
      );
    });
  });

  describe('useDeleteTask', () => {
    it('deletes the task and does not parse the empty 204 body', async () => {
      const response = noContentResponse();
      mockFetch.mockResolvedValueOnce(response);

      const { result } = renderHook(() => useDeleteTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('1');

      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/1', {
        method: 'DELETE',
        credentials: 'include',
      });
      expect(response.json).not.toHaveBeenCalled();
    });

    it('refreshes the journal listings and the upcoming window', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useDeleteTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('1');

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.journalLists(),
          taskKeys.upcoming(),
        ]);
      });
      expect(toast.success).toHaveBeenCalledWith('Task deleted successfully');
    });

    it('drops the deleted task from the cache instead of invalidating it', async () => {
      queryClient.setQueryData(taskKeys.detail('1'), taskReadResponse());
      mockFetch.mockResolvedValueOnce(noContentResponse());

      const { result } = renderHook(() => useDeleteTask(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync('1');

      // Not merely stale: gone. An invalidated entry stays readable for the
      // app-wide staleTime, so a useTask mounting afterwards would render a
      // deleted task from cache without issuing a request.
      await waitFor(() => {
        expect(queryClient.getQueryData(taskKeys.detail('1'))).toBeUndefined();
      });
    });
  });

  describe('task contact links', () => {
    it('links a contact as a bare resource identifier', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());

      const { result } = renderHook(() => useLinkTaskContact(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', contactId: '3' });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tasks/1/relationships/contacts',
        expect.objectContaining({ method: 'POST' })
      );
      expect(requestBody()).toEqual({ data: { type: 'contacts', id: '3' } });
    });

    it('unlinks a contact by id', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());

      const { result } = renderHook(() => useUnlinkTaskContact(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', contactId: '3' });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tasks/1/relationships/contacts/3',
        { method: 'DELETE', credentials: 'include' }
      );
    });

    it('refreshes the task, the journal listings, the upcoming window and its history', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useLinkTaskContact(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', contactId: '3' });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.detail('1'),
          taskKeys.journalLists(),
          taskKeys.upcoming(),
          taskHistoryKeys.forTask('1'),
        ]);
      });
      expect(toast.success).toHaveBeenCalledWith('Contact linked successfully');
    });

    it('refreshes the same four namespaces when unlinking', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useUnlinkTaskContact(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', contactId: '3' });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.detail('1'),
          taskKeys.journalLists(),
          taskKeys.upcoming(),
          taskHistoryKeys.forTask('1'),
        ]);
      });
      expect(toast.success).toHaveBeenCalledWith(
        'Contact unlinked successfully'
      );
    });
  });

  describe('task intermediate journal links', () => {
    it('attaches a journal as a bare resource identifier', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());

      const { result } = renderHook(() => useAttachTaskIntermediateJournal(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', journalId: '9' });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tasks/1/relationships/intermediate-journals',
        expect.objectContaining({ method: 'POST' })
      );
      expect(requestBody()).toEqual({ data: { type: 'journals', id: '9' } });
    });

    it('detaches a journal by id', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());

      const { result } = renderHook(() => useDetachTaskIntermediateJournal(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', journalId: '9' });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/tasks/1/relationships/intermediate-journals/9',
        { method: 'DELETE', credentials: 'include' }
      );
    });

    it('leaves the upcoming window alone — a mention cannot move a due date', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useAttachTaskIntermediateJournal(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', journalId: '9' });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.detail('1'),
          taskKeys.journalLists(),
        ]);
      });
      expect(invalidatedKeys(invalidateSpy)).not.toContainEqual(
        taskKeys.upcoming()
      );
      expect(toast.success).toHaveBeenCalledWith('Journal linked successfully');
    });

    it('leaves the upcoming window alone when detaching too', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

      const { result } = renderHook(() => useDetachTaskIntermediateJournal(), {
        wrapper: createWrapper,
      });

      await result.current.mutateAsync({ taskId: '1', journalId: '9' });

      await waitFor(() => {
        expect(invalidatedKeys(invalidateSpy)).toEqual([
          taskKeys.detail('1'),
          taskKeys.journalLists(),
        ]);
      });
      expect(invalidatedKeys(invalidateSpy)).not.toContainEqual(
        taskKeys.upcoming()
      );
      expect(toast.success).toHaveBeenCalledWith(
        'Journal unlinked successfully'
      );
    });

    it('surfaces the refusal to detach an anchor journal', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(
          409,
          'TASK_JOURNAL_IS_ANCHOR',
          'Journal 42 is the due journal; retarget the task instead'
        )
      );

      const { result } = renderHook(() => useDetachTaskIntermediateJournal(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ taskId: '1', journalId: '42' })
      ).rejects.toMatchObject({ code: 'TASK_JOURNAL_IS_ANCHOR' });

      expect(toast.error).toHaveBeenCalledWith(
        'Journal 42 is the due journal; retarget the task instead'
      );
    });

    /**
     * The attach picker excludes tasks already linked to the journal being
     * viewed, but it computes that from a cache which can be stale — a task
     * retargeted onto this journal elsewhere is an anchor here by the time the
     * request lands. The refusal is therefore a field-level answer the dialog
     * renders, not a failure, so it needs the code as a constant rather than as
     * a string spelled out at the call site.
     */
    it('names the anchor refusal as an exported code', () => {
      expect(TASK_JOURNAL_IS_ANCHOR).toBe('TASK_JOURNAL_IS_ANCHOR');
    });

    it('surfaces the refusal to attach an anchor journal under that code', async () => {
      mockFetch.mockResolvedValueOnce(
        errorResponse(
          409,
          TASK_JOURNAL_IS_ANCHOR,
          'Journal 42 is the creating journal of task 1'
        )
      );

      const { result } = renderHook(() => useAttachTaskIntermediateJournal(), {
        wrapper: createWrapper,
      });

      await expect(
        result.current.mutateAsync({ taskId: '1', journalId: '42' })
      ).rejects.toMatchObject({ code: TASK_JOURNAL_IS_ANCHOR });
    });
  });

  /**
   * `TASK_VALIDATION_ERROR` is one code covering several fields, so unlike the
   * three refusals above it cannot be placed on a form field from the code
   * alone. The backend sends the field as `meta.field`; this reads it from
   * there rather than out of the message's `"{field}: ..."` prefix, which a
   * rewording would break silently.
   */
  describe('the field a validation refusal is about', () => {
    it('names the validation code and the contact one as exported codes', () => {
      expect(TASK_VALIDATION_ERROR).toBe('TASK_VALIDATION_ERROR');
      expect(CONTACT_NOT_FOUND).toBe('CONTACT_NOT_FOUND');
    });

    it('reads the field out of the error meta', () => {
      const error = new TaskApiError(
        'text: Task text is required',
        400,
        TASK_VALIDATION_ERROR,
        { field: 'text' }
      );

      expect(taskValidationField(error)).toBe('text');
    });

    it('reads whichever field the refusal named', () => {
      const error = new TaskApiError(
        'due_journal_id: A journal anchor is required',
        400,
        TASK_VALIDATION_ERROR,
        { field: 'due_journal_id' }
      );

      expect(taskValidationField(error)).toBe('due_journal_id');
    });

    it('answers nothing for a different refusal', () => {
      const error = new TaskApiError(
        'The due journal is not dated after today',
        400,
        TASK_DUE_JOURNAL_NOT_FUTURE,
        { field: 'due_journal_id' }
      );

      expect(taskValidationField(error)).toBeNull();
    });

    it('answers nothing when the refusal carried no meta', () => {
      const error = new TaskApiError(
        'text: Task text is required',
        400,
        TASK_VALIDATION_ERROR
      );

      expect(taskValidationField(error)).toBeNull();
    });

    it('answers nothing for a meta whose field is not a string', () => {
      const error = new TaskApiError('nope', 400, TASK_VALIDATION_ERROR, {
        field: 7,
      });

      expect(taskValidationField(error)).toBeNull();
    });

    it('answers nothing for an error that is not the task client’s', () => {
      expect(taskValidationField(new Error('network down'))).toBeNull();
      expect(taskValidationField(undefined)).toBeNull();
    });

    it('carries the meta through from the response body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: jest.fn().mockResolvedValue({
          errors: [
            {
              status: '400',
              code: TASK_VALIDATION_ERROR,
              detail: 'text: Task text is required',
              meta: { field: 'text' },
            },
          ],
        }),
      } as unknown as Response);

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: createWrapper,
      });

      const rejection = await result.current
        .mutateAsync({ journalId: '7', text: '   ', due_journal_id: 42 })
        .catch((error: unknown) => error);

      expect(taskValidationField(rejection)).toBe('text');
    });
  });

  describe('cancel-before-invalidate', () => {
    /**
     * Issue #1203 and the `fetchNextPage` race cost iteration 17 two bug fixes
     * to establish that a mutation must cancel in-flight fetches before
     * invalidating them. Every mutation on this client is held to it, not just
     * the one that happened to be written first.
     */
    const mutations: ReadonlyArray<{
      name: string;
      run: () => Promise<unknown>;
      response: () => Response;
      /**
       * Cancels an optimistic handler makes on its own, before the refresh
       * helper's.
       *
       * The count guard below is what stops this test passing vacuously — a
       * hook using bare `invalidateQueries` would leave `cancelSpy` with no
       * calls at all, `Math.max()` of nothing is `-Infinity`, and the ordering
       * assertion would hold for the wrong reason. Loosening it to `>=` for
       * the optimistic hooks would give that vacuity straight back, so the
       * expected surplus is *stated per hook* instead.
       */
      optimisticCancels?: number;
    }> = [
      {
        name: 'useCreateTask',
        response: () => jsonResponse(taskWriteResponse(), 201),
        run: async () => {
          const { result } = renderHook(() => useCreateTask(), {
            wrapper: createWrapper,
          });
          return result.current.mutateAsync({
            journalId: '7',
            text: 'Print the permit',
            due_journal_id: 42,
          });
        },
      },
      {
        name: 'useUpdateTask',
        response: () => jsonResponse(taskWriteResponse()),
        optimisticCancels: 1,
        run: async () => {
          const { result } = renderHook(() => useUpdateTask(), {
            wrapper: createWrapper,
          });
          return result.current.mutateAsync({
            taskId: '1',
            status: TaskStatus.DONE,
          });
        },
      },
      {
        name: 'useRetargetTask',
        response: () => jsonResponse(taskWriteResponse()),
        run: async () => {
          const { result } = renderHook(() => useRetargetTask(), {
            wrapper: createWrapper,
          });
          return result.current.mutateAsync({
            taskId: '1',
            due_journal_id: 99,
          });
        },
      },
      {
        name: 'useDeleteTask',
        response: noContentResponse,
        run: async () => {
          const { result } = renderHook(() => useDeleteTask(), {
            wrapper: createWrapper,
          });
          return result.current.mutateAsync('1');
        },
      },
      {
        name: 'useLinkTaskContact',
        response: noContentResponse,
        run: async () => {
          const { result } = renderHook(() => useLinkTaskContact(), {
            wrapper: createWrapper,
          });
          return result.current.mutateAsync({ taskId: '1', contactId: '3' });
        },
      },
      {
        name: 'useUnlinkTaskContact',
        response: noContentResponse,
        run: async () => {
          const { result } = renderHook(() => useUnlinkTaskContact(), {
            wrapper: createWrapper,
          });
          return result.current.mutateAsync({ taskId: '1', contactId: '3' });
        },
      },
      {
        name: 'useAttachTaskIntermediateJournal',
        response: noContentResponse,
        run: async () => {
          const { result } = renderHook(
            () => useAttachTaskIntermediateJournal(),
            {
              wrapper: createWrapper,
            }
          );
          return result.current.mutateAsync({ taskId: '1', journalId: '9' });
        },
      },
      {
        name: 'useDetachTaskIntermediateJournal',
        response: noContentResponse,
        run: async () => {
          const { result } = renderHook(
            () => useDetachTaskIntermediateJournal(),
            {
              wrapper: createWrapper,
            }
          );
          return result.current.mutateAsync({ taskId: '1', journalId: '9' });
        },
      },
    ];

    it.each(mutations)(
      '$name cancels every in-flight fetch before invalidating any of them',
      async ({ run, response, optimisticCancels = 0 }) => {
        mockFetch.mockResolvedValueOnce(response());
        const cancelSpy = jest.spyOn(queryClient, 'cancelQueries');
        const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');

        await run();

        await waitFor(() => {
          expect(invalidateSpy).toHaveBeenCalled();
        });
        expect(cancelSpy).toHaveBeenCalledTimes(
          invalidateSpy.mock.calls.length + optimisticCancels
        );
        expect(lastCallOrder(cancelSpy)).toBeLessThan(
          firstCallOrder(invalidateSpy)
        );
      }
    );

    it('never invalidates the cache directly, only through the helper', () => {
      const source = readFileSync(join(__dirname, '..', 'tasks.ts'), 'utf8');

      expect(source).not.toMatch(/invalidateQueries\(/);
    });
  });

  describe('no mutation retries', () => {
    /**
     * `lib/providers.tsx` retries every mutation once, a second later. These
     * tests therefore build a client carrying *that* default rather than the
     * suite's `retry: false`, so they fail if the hooks stop opting out.
     */
    const retryingWrapper = ({ children }: { children: ReactNode }) =>
      React.createElement(
        QueryClientProvider,
        {
          client: new QueryClient({
            defaultOptions: {
              queries: { retry: false },
              mutations: { retry: 1, retryDelay: 0 },
            },
          }),
        },
        children
      );

    it('asks for a confirmation once, not twice, when a done task needs reopening', async () => {
      mockFetch.mockResolvedValue(
        errorResponse(
          409,
          'TASK_REOPEN_NOT_ACKNOWLEDGED',
          'This task is done; confirm that reopening it is intended'
        )
      );

      const { result } = renderHook(() => useRetargetTask(), {
        wrapper: retryingWrapper,
      });

      await expect(
        result.current.mutateAsync({ taskId: '1', due_journal_id: 99 })
      ).rejects.toMatchObject({ code: 'TASK_REOPEN_NOT_ACKNOWLEDGED' });

      // A retry would delay the caller's confirmation dialog by the retry
      // delay and log a second refusal for every one the user resolves.
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('never sends a create twice', async () => {
      mockFetch.mockResolvedValue(
        errorResponse(500, 'INTERNAL_ERROR', 'Something went wrong')
      );

      const { result } = renderHook(() => useCreateTask(), {
        wrapper: retryingWrapper,
      });

      await expect(
        result.current.mutateAsync({
          journalId: '7',
          text: 'Print the permit',
          due_journal_id: 42,
        })
      ).rejects.toBeInstanceOf(TaskApiError);

      // Creating a task is not idempotent: a POST that succeeded on the server
      // but lost its response would record the same commitment twice.
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });
});
