/**
 * The tasks on a list: reading its open and completed tasks, creating one at
 * the bottom, reordering, moving a task onto or between lists, and taking it
 * off its list.
 *
 * A list's tasks are task resources, so their cache lives under `taskKeys`
 * (`openOnList`, `completedOnList`) and every task write's optimistic patch
 * reaches them. The writes here are task writes — they carry `TASK_WRITE` and
 * refresh through the same helpers as `tasks.ts` — except the reorder, which
 * changes nothing but order and so deliberately is not one (see
 * {@link useReorderListTask}).
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import type {
  CompletedListTasksResponse,
  ListTaskCreateInput,
  ListTaskReorderInput,
  ListTasksResponse,
  TaskCollectionResponse,
  TaskMoveInput,
  TaskReadResponse,
  TaskResponse,
} from '@/types/tasks';
import { REFRESH_CONTACT_HISTORY } from './contact-history-keys';
import { invalidateAfterMutation } from './invalidate-after-mutation';
import { moveAfter, orderByIds } from './cached-order';
import {
  cancelReadInFlight,
  isNewestMove,
  settleMove,
  startMove,
  takeRereadNeeded,
} from './move-sequence';
import { TASK_LIST_CHANGED } from './task-lists';
import {
  deferSharedRefresh,
  isLastTaskWrite,
  JSON_HEADERS,
  NO_RETRY,
  readJson,
  refreshTaskAndDueCounts,
  refreshTaskCollections,
  repaidSharedRefresh,
  reportFailure,
  retryReadUnlessRefused,
  settleTaskWrite,
  TASK_WRITE,
  TaskApiError,
  taskHistoryKeys,
  taskKeys,
  taskStoreScope,
} from './tasks';

/** A list task's due day is before today in the user's timezone. */
export const TASK_DUE_DATE_IN_PAST = 'TASK_DUE_DATE_IN_PAST';

/**
 * Only a task holding both a creating and a due journal can leave its list —
 * it becomes journal-only. One that cannot is moved, cancelled or deleted
 * instead.
 */
export const TASK_LIST_REMOVAL_NEEDS_JOURNALS =
  'TASK_LIST_REMOVAL_NEEDS_JOURNALS';

/**
 * The key every task reorder carries — and **not** `TASK_WRITE_KEY`.
 *
 * A reorder changes nothing a task write's refresh covers: it records no
 * history and moves no count, journal row or dashboard row. Counted as a task
 * write it would hold back a status change's refresh for the length of a drag,
 * and the dashboard's on-load summary read would wait on it. Its own key is
 * also how an answer knows a newer reorder has been made since.
 */
export const TASK_REORDER_KEY = ['task-reorder'] as const;

/** The page size the *Completed* group reads in, unless told otherwise. */
const COMPLETED_PAGE_SIZE = 20;

/** A JSON integer for a resource id, which the write bodies require. */
const toId = (id: string) => Number(id);

// API Functions

async function fetchOpenTasks(listId: string): Promise<ListTasksResponse> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.TASKS(listId), {
    credentials: 'include',
  });
  return readJson<ListTasksResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function fetchCompletedTasks(
  listId: string,
  page: number,
  limit: number
): Promise<CompletedListTasksResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    limit: limit.toString(),
  });
  const response = await fetch(
    `${API_ENDPOINTS.TASK_LISTS.COMPLETED_TASKS(listId)}?${params.toString()}`,
    { credentials: 'include' }
  );
  return readJson<CompletedListTasksResponse>(
    response,
    ERROR_MESSAGES.FETCH_FAILED
  );
}

async function createListTask({
  listId,
  text,
  due_date,
  due_journal_id,
  contact_ids,
}: ListTaskCreateInput): Promise<TaskResponse> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.TASKS(listId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'tasks',
        // The attributes forbid extras, so "none" is the absence of a field.
        attributes: {
          text,
          ...(due_date !== undefined ? { due_date } : {}),
          ...(due_journal_id !== undefined ? { due_journal_id } : {}),
          ...(contact_ids?.length ? { contact_ids } : {}),
        },
      },
    }),
  });
  return readJson<TaskResponse>(response, ERROR_MESSAGES.CREATE_FAILED);
}

async function reorderListTask({
  taskId,
  afterTaskId,
}: ListTaskReorderInput): Promise<TaskCollectionResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.REORDER(taskId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'task-reorders',
        // Required, and `null` is the top: omitting it is refused.
        attributes: {
          after_task_id: afterTaskId === null ? null : toId(afterTaskId),
        },
      },
    }),
  });
  return readJson<TaskCollectionResponse>(
    response,
    ERROR_MESSAGES.UPDATE_FAILED
  );
}

async function moveTaskToList({
  taskId,
  taskListId,
}: TaskMoveInput): Promise<TaskResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.MOVE(taskId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'task-moves',
        attributes: { task_list_id: toId(taskListId) },
      },
    }),
  });
  return readJson<TaskResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function removeTaskFromList(taskId: string): Promise<TaskReadResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.REMOVE_FROM_LIST(taskId), {
    method: 'POST',
    credentials: 'include',
  });
  return readJson<TaskReadResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

/**
 * A task's list changing: both lists, their counts, the task's reads and the
 * contact history, which labels a task with its list.
 *
 * On settle rather than success, so a failure refreshes too. The shared
 * collections — the lists, the journals, the dashboard — are refreshed only by
 * the last task write standing, as `useUpdateTask` does: refetching them while
 * another write is out would bring back a row its optimistic patch removed,
 * and that write refreshes them when it settles. But it refreshes them for
 * *its* task only, so this task's own detail and history, and the contact
 * history this move relabels, are refreshed here whatever else is pending.
 */
function refreshAfterListChange(queryClient: QueryClient, taskId: string) {
  if (isLastTaskWrite(queryClient)) {
    repaidSharedRefresh(queryClient);
    void refreshTaskAndDueCounts(queryClient, taskId, REFRESH_CONTACT_HISTORY);
    return;
  }

  // The shared refresh is owed to whichever task write settles last.
  deferSharedRefresh(queryClient);

  void invalidateAfterMutation(
    queryClient,
    { queryKey: taskKeys.detail(taskId) },
    { queryKey: taskHistoryKeys.forTask(taskId) },
    REFRESH_CONTACT_HISTORY
  );
}

// Hooks

/**
 * A list's open tasks in the user's manual order, each read whole. Archived
 * lists are readable; each row's `task_list.archived` says so.
 */
export function useTaskListOpenTasks(listId: string) {
  return useQuery({
    queryKey: taskKeys.openOnList(listId),
    queryFn: () => fetchOpenTasks(listId),
    enabled: !!listId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: retryReadUnlessRefused,
  });
}

/**
 * A list's done and cancelled tasks, most recently closed first, a page at a
 * time — the list page's collapsed *Completed* group.
 *
 * Paged by page **number** from `meta`, never by following `links.next`: the
 * backend builds its links as absolute URLs from its own base URL, which need
 * not be the origin the browser reaches it through.
 */
export function useTaskListCompletedTasks(
  listId: string,
  { limit = COMPLETED_PAGE_SIZE }: { limit?: number } = {}
) {
  return useInfiniteQuery({
    queryKey: taskKeys.completedOnList(listId, limit),
    queryFn: ({ pageParam }) => fetchCompletedTasks(listId, pageParam, limit),
    initialPageParam: 1,
    getNextPageParam: ({ meta }) =>
      meta.current_page < meta.page_count ? meta.current_page + 1 : undefined,
    enabled: !!listId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/** Creates a task at the bottom of a list, in no journal. */
export function useCreateListTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: createListTask,
    onSuccess: (_, { contact_ids }) => {
      // The list's own open tasks are under `onLists()`, which this names, as
      // is its count on the listings. A due journal's badge moves too, and
      // each linked contact's feed gains a row.
      void refreshTaskCollections(
        queryClient,
        ...(contact_ids?.length ? [REFRESH_CONTACT_HISTORY] : [])
      );
      toast.success(SUCCESS_MESSAGES.TASK_CREATED);
    },
    onError: reportFailure,
    onSettled: () => settleTaskWrite(queryClient, { countsItself: false }),
  });
}

/** Re-orders one list's cached open tasks, moving rows and never rewriting them. */
function orderOpenTasks(
  queryClient: QueryClient,
  listId: string,
  ids: readonly string[]
): boolean {
  let matched = true;
  queryClient.setQueryData<ListTasksResponse>(
    taskKeys.openOnList(listId),
    cached => {
      if (!cached) return cached;
      const ordered = orderByIds(cached.data, ids);
      matched = ordered.matched;
      return { ...cached, data: ordered.items };
    }
  );
  return matched;
}

/** The cached order a reorder writes to: one list's open tasks. */
const reorderScope = (listId: string) => `list-tasks:${listId}`;

/**
 * Moves an open task to the top of its list, or directly after another open
 * task on it — the list page's drag and its keyboard equivalent.
 *
 * - **Optimistic.** The row moves at once, so a drop never snaps back while
 *   it waits.
 * - **The answer orders the rows; it never replaces them.** It is the list's
 *   open tasks in the write shape — no journals, contacts or `overdue` — so
 *   the cached read models are re-sorted by its ids and kept.
 * - **Overlapping reorders on a list settle together** (`move-sequence.ts`):
 *   only the last to settle, and only if it is also the newest, takes the
 *   answer. Anything else re-reads the list, since each reorder's snapshot may
 *   hold another's unconfirmed order. A lone failed reorder first puts back
 *   **only the order** — a status ticked on another row meanwhile is that
 *   write's to keep or undo. Each list settles on its own.
 * - The list is re-read too when the answer names other tasks than the cache,
 *   or when a reorder's cancel cut short a refresh already in flight.
 * - **`TASK_LIST_CHANGED` is not reported as a failure.** Another request
 *   changed the list while this waited; the list is re-read and the error
 *   carries the code, so the caller can try again against the fresh order.
 *
 * Accepted: a task write's refetch landing while a reorder is in flight shows
 * the server's previous order until the reorder's answer re-sorts it.
 */
export function useReorderListTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationKey: TASK_REORDER_KEY,
    mutationFn: reorderListTask,
    onMutate: async ({ listId, taskId, afterTaskId }) => {
      const key = taskKeys.openOnList(listId);
      const ticket = startMove(
        queryClient,
        reorderScope(listId),
        queryClient.getQueryState(key)?.fetchStatus === 'fetching'
      );
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient
        .getQueryData<ListTasksResponse>(key)
        ?.data.map(task => task.id);

      queryClient.setQueryData<ListTasksResponse>(key, cached =>
        cached
          ? { ...cached, data: moveAfter(cached.data, taskId, afterTaskId) }
          : cached
      );

      return { previous, ticket };
    },
    onError: (error: Error) => {
      if (error instanceof TaskApiError && error.code === TASK_LIST_CHANGED) {
        return;
      }
      reportFailure(error);
    },
    onSettled: async (answer, error, { listId }, context) => {
      const scope = reorderScope(listId);
      // Any other pending reorder on this list will settle later and decide.
      if (!settleMove(queryClient, scope)) return;

      const newest =
        context !== undefined &&
        isNewestMove(queryClient, scope, context.ticket);
      // Overlapping reorders may have been applied in either order, so even
      // the newest answer is shown and then confirmed.
      let reread = takeRereadNeeded(queryClient, scope);
      // A read started mid-drag may hold the old order and land after this.
      if (await cancelReadInFlight(queryClient, taskKeys.openOnList(listId))) {
        reread = true;
      }

      if (!error && answer && newest) {
        const matched = orderOpenTasks(
          queryClient,
          listId,
          answer.data.map(task => task.id)
        );
        reread = !matched || reread;
      } else {
        if (error && newest && context?.previous) {
          orderOpenTasks(queryClient, listId, context.previous);
        }
        reread = true;
      }

      if (reread) {
        void invalidateAfterMutation(queryClient, {
          queryKey: taskKeys.openOnList(listId),
        });
      }
    },
  });
}

/**
 * Puts a task on one of the user's lists, or moves it to another; it joins the
 * bottom. A journal-only task keeps its journals and stops lapsing.
 *
 * Both lists' open tasks and counts refresh through `onLists()` and the
 * listings; the contact history labels a task with its list, so it does too.
 */
export function useMoveTaskToList() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: moveTaskToList,
    onSuccess: () => {
      toast.success(SUCCESS_MESSAGES.TASK_MOVED_TO_LIST);
    },
    onError: reportFailure,
    onSettled: (_data, _error, { taskId }) => {
      refreshAfterListChange(queryClient, taskId);
    },
  });
}

/**
 * Takes a task off its list, making it journal-only. Only a task holding both a
 * creating and a due journal can leave (`TASK_LIST_REMOVAL_NEEDS_JOURNALS`
 * otherwise).
 *
 * Answers with the task's **read model**, which is stored and returned: its
 * `lapsed` says whether the task is lapsed the moment it leaves. Warning the
 * user *before* confirming is the caller's, from the due journal's date it
 * already shows.
 */
export function useRemoveTaskFromList() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: removeTaskFromList,
    onMutate: (taskId: string) => ({
      ticket: startMove(queryClient, taskStoreScope(taskId), false),
    }),
    onSuccess: (answer, taskId, context) => {
      // Not if the task was deleted, or written again, since this started:
      // a late answer would recreate a detail that is gone or stale.
      if (
        context &&
        isNewestMove(queryClient, taskStoreScope(taskId), context.ticket)
      ) {
        queryClient.setQueryData(taskKeys.detail(taskId), answer);
      }
      toast.success(SUCCESS_MESSAGES.TASK_REMOVED_FROM_LIST);
    },
    onError: reportFailure,
    onSettled: (_data, _error, taskId) => {
      settleMove(queryClient, taskStoreScope(taskId));
      refreshAfterListChange(queryClient, taskId);
    },
  });
}
