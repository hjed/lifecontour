/**
 * Task lists: reading them, and creating, renaming, reordering, archiving and
 * deleting them.
 *
 * Lists are part of the tasks domain, so their refusals use the task error
 * codes and throw {@link TaskApiError}. Their cache lives under `taskListKeys`,
 * a root of its own (see `task-list-keys.ts` for why), and every write names
 * the task namespaces it reaches explicitly: a list's name, icon and archived
 * state are embedded in every task read as `task_list`, and in the contact
 * history's task rows.
 *
 * The tasks *on* a list are read and written through `list-tasks.ts`.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type Query,
  type QueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import type { HistoryFilters, HistoryListResponse } from '@/types/history';
import type {
  TaskListCreateInput,
  TaskListMoveInput,
  TaskListMoveResponse,
  TaskListResponse,
  TaskListsPageResponse,
  TaskListsResponse,
  TaskListUpdateInput,
} from '@/types/task-lists';
import { historyKeys } from './contacts';
import { homeDashboardKeys } from './home-dashboard';
import { invalidateAfterMutation } from './invalidate-after-mutation';
import { journalKeys } from './journal-keys';
import { moveToIndex, orderByIds } from './cached-order';
import {
  cancelReadInFlight,
  isNewestMove,
  settleMove,
  startMove,
  takeRereadNeeded,
} from './move-sequence';
import {
  taskListHistoryKeys,
  taskListKeys,
  type TaskListListingParams,
} from './task-list-keys';
import {
  expectNoContent,
  JSON_HEADERS,
  NO_RETRY,
  readJson,
  reportFailure,
  taskHistoryKeys,
  taskKeys,
} from './tasks';

/** The list does not exist, or is not the user's — the two are indistinguishable. */
export const TASK_LIST_NOT_FOUND = 'TASK_LIST_NOT_FOUND';

/**
 * The list is archived, and so read-only until unarchived. Answered to every
 * write on the list or on a task on it; the way out is unarchiving.
 */
export const TASK_LIST_ARCHIVED = 'TASK_LIST_ARCHIVED';

/**
 * Another request changed the list while this one waited for it. Not a
 * failure the user caused: re-read and, if it still makes sense, try again.
 */
export const TASK_LIST_CHANGED = 'TASK_LIST_CHANGED';

/**
 * The key every list move carries. Its count of pending moves is how a move's
 * answer knows a newer move has been made since, and must not be applied over
 * it.
 */
export const TASK_LIST_MOVE_KEY = ['task-list-move'] as const;

const ACTIVE_LISTING = taskListKeys.listing({ archived: 'active' });

/**
 * A name-filtered `active` listing: in the manual order, like the active
 * listing, but never patched by a move, so a move re-reads it.
 */
function isNamedActiveListing({ queryKey }: Query): boolean {
  const params = queryKey[2];
  return (
    typeof params === 'object' &&
    params !== null &&
    'archived' in params &&
    params.archived === 'active' &&
    'name' in params
  );
}

// API Functions

/** The listing's query string; a blank name is left out rather than refused. */
function listingQuery(
  { archived, name }: TaskListListingParams,
  page?: { page: number; limit: number }
): string {
  const params = new URLSearchParams({ archived });
  const trimmed = name?.trim();
  if (trimmed) params.append('name', trimmed);
  if (page) {
    params.append('page', page.page.toString());
    params.append('limit', page.limit.toString());
  }
  return `${API_ENDPOINTS.TASK_LISTS.BASE}?${params.toString()}`;
}

async function fetchTaskLists(
  listing: TaskListListingParams
): Promise<TaskListsResponse> {
  const response = await fetch(listingQuery(listing), {
    credentials: 'include',
  });
  return readJson<TaskListsResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function fetchTaskListsPage(
  listing: TaskListListingParams,
  page: number,
  limit: number
): Promise<TaskListsPageResponse> {
  const response = await fetch(listingQuery(listing, { page, limit }), {
    credentials: 'include',
  });
  return readJson<TaskListsPageResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function fetchTaskList(listId: string): Promise<TaskListResponse> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.BY_ID(listId), {
    credentials: 'include',
  });
  return readJson<TaskListResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function fetchTaskListHistory(
  listId: string,
  { page, limit }: HistoryFilters
): Promise<HistoryListResponse> {
  const params = new URLSearchParams();
  if (page) params.append('page', page.toString());
  if (limit) params.append('limit', limit.toString());

  const response = await fetch(
    `${API_ENDPOINTS.TASK_LISTS.HISTORY(listId)}?${params.toString()}`,
    { credentials: 'include' }
  );
  return readJson<HistoryListResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function createTaskList({
  name,
  icon,
}: TaskListCreateInput): Promise<TaskListResponse> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.BASE, {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'task-lists',
        // No icon is the absence of the field: the attributes forbid extras.
        attributes: { name, ...(icon !== undefined ? { icon } : {}) },
      },
    }),
  });
  return readJson<TaskListResponse>(response, ERROR_MESSAGES.CREATE_FAILED);
}

async function updateTaskList({
  listId,
  name,
  icon,
}: TaskListUpdateInput): Promise<TaskListResponse> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.BY_ID(listId), {
    method: 'PATCH',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'task-lists',
        // The backend refuses a body id that disagrees with the path.
        id: listId,
        // Only what changed. `icon: null` clears the icon; an absent icon
        // leaves it alone, so the two must not be collapsed.
        attributes: {
          ...(name !== undefined ? { name } : {}),
          ...(icon !== undefined ? { icon } : {}),
        },
      },
    }),
  });
  return readJson<TaskListResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function moveTaskList({
  listId,
  index,
}: TaskListMoveInput): Promise<TaskListMoveResponse> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.MOVE(listId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: { type: 'task-list-moves', attributes: { index } },
    }),
  });
  return readJson<TaskListMoveResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

/** Archive and unarchive are actions with no body, and idempotent. */
async function setArchived(
  listId: string,
  archived: boolean
): Promise<TaskListResponse> {
  const url = archived
    ? API_ENDPOINTS.TASK_LISTS.ARCHIVE(listId)
    : API_ENDPOINTS.TASK_LISTS.UNARCHIVE(listId);
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
  });
  return readJson<TaskListResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function deleteTaskList(listId: string): Promise<void> {
  const response = await fetch(API_ENDPOINTS.TASK_LISTS.BY_ID(listId), {
    method: 'DELETE',
    credentials: 'include',
  });
  return expectNoContent(response, ERROR_MESSAGES.DELETE_FAILED);
}

// Cache refreshes

/**
 * A change to a list's own attributes: everything that shows them.
 *
 * - every listing, whichever filter (an archive moves the list between them);
 * - every task read, because each embeds its list as `task_list`;
 * - the home dashboard, whose task rows carry `task_list` too;
 * - the contact history, whose task rows are labelled with their list;
 * - the list's own history, which the write has just added to.
 */
function listChangeFilters(listId: string) {
  return [
    { queryKey: taskListKeys.listings() },
    { queryKey: taskKeys.all },
    { queryKey: homeDashboardKeys.all },
    { queryKey: historyKeys.all },
    { queryKey: taskListHistoryKeys.forList(listId) },
  ];
}

function refreshList(queryClient: QueryClient, listId: string): Promise<void> {
  return invalidateAfterMutation(queryClient, ...listChangeFilters(listId));
}

/**
 * Stores a write's answer as the list's detail. Never into a listing: it
 * carries no count.
 *
 * A read of the detail that started before the write would otherwise land
 * after it and put the old name or archived state back, fresh for the whole
 * `staleTime`. Cancelling first discards that read — the answer is newer.
 */
async function storeList(
  queryClient: QueryClient,
  answer: TaskListResponse
): Promise<void> {
  const key = taskListKeys.detail(answer.data.id);
  await queryClient.cancelQueries({ queryKey: key, exact: true });
  queryClient.setQueryData(key, answer);
}

/** The scope overlapping writes to one list are sequenced in. */
const listWriteScope = (listId: string) => `task-list:${listId}`;

/**
 * What a rename, an icon change, an archive and an unarchive do around their
 * request, so overlapping writes to one list cannot leave an old answer
 * standing.
 *
 * Two writes to a list may commit in one order and answer in the other: a
 * rename committed before an archive but answering after it would store its
 * `archived: false` over the confirmed archive. So only the **newest** write's
 * answer is stored, and if writes overlapped the last to settle re-reads the
 * list — answer order cannot say which committed last (`move-sequence.ts`).
 * A lone write stores its answer with no re-read.
 */
function listWriteCallbacks<TVariables>(
  queryClient: QueryClient,
  listIdOf: (variables: TVariables) => string,
  wording: string
) {
  return {
    onMutate: (variables: TVariables) => ({
      ticket: startMove(
        queryClient,
        listWriteScope(listIdOf(variables)),
        false
      ),
    }),
    onSuccess: async (
      answer: TaskListResponse,
      variables: TVariables,
      context: { ticket: number } | undefined
    ) => {
      const listId = listIdOf(variables);
      if (
        context &&
        isNewestMove(queryClient, listWriteScope(listId), context.ticket)
      ) {
        await storeList(queryClient, answer);
      }
      void refreshList(queryClient, listId);
      toast.success(wording);
    },
    onError: reportFailure,
    onSettled: (
      _answer: TaskListResponse | undefined,
      _error: Error | null,
      variables: TVariables
    ) => settleListWrite(queryClient, listIdOf(variables)),
  };
}

/**
 * A list write settling: once it is the last one on the list, re-read the
 * list if writes overlapped. A deleted list's detail has been removed, so the
 * re-read finds nothing to refetch.
 */
function settleListWrite(queryClient: QueryClient, listId: string): void {
  const scope = listWriteScope(listId);
  if (!settleMove(queryClient, scope)) return;
  if (takeRereadNeeded(queryClient, scope)) {
    void invalidateAfterMutation(queryClient, {
      queryKey: taskListKeys.detail(listId),
    });
  }
}

// Hooks

/**
 * The user's lists, each with its open-task count.
 *
 * `active` (the default) and `all` come in the user's manual order; `archived`
 * comes most recently archived first.
 */
export function useTaskLists(params: Partial<TaskListListingParams> = {}) {
  const name = params.name?.trim();
  const listing: TaskListListingParams = {
    archived: params.archived ?? 'active',
    ...(name ? { name } : {}),
  };
  return useQuery({
    queryKey: taskListKeys.listing(listing),
    queryFn: () => fetchTaskLists(listing),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/** How many archived lists a page of the archived lists page holds. */
export const ARCHIVED_LISTS_PAGE_SIZE = 20;

/**
 * The user's archived lists, most recently archived first, a page at a time,
 * each with its open-task count: the archived lists page.
 *
 * `name` keeps lists whose name contains it, ignoring case; it is trimmed and,
 * when blank, left out. Pages follow `meta`, so `fetchNextPage` loads the next
 * one and `hasNextPage` turns false on the last.
 */
export function useArchivedTaskLists({
  name,
  limit = ARCHIVED_LISTS_PAGE_SIZE,
}: { name?: string; limit?: number } = {}) {
  const trimmed = name?.trim() || undefined;
  return useInfiniteQuery({
    queryKey: taskListKeys.archivedPages({ name: trimmed, limit }),
    queryFn: ({ pageParam }) =>
      fetchTaskListsPage(
        { archived: 'archived', name: trimmed },
        pageParam,
        limit
      ),
    initialPageParam: 1,
    getNextPageParam: ({ meta }) =>
      meta.current_page < meta.page_count ? meta.current_page + 1 : undefined,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/** One list. An archived list is still readable; it is only read-only. */
export function useTaskList(listId: string) {
  return useQuery({
    queryKey: taskListKeys.detail(listId),
    queryFn: () => fetchTaskList(listId),
    enabled: !!listId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * A list's change history, most recent first.
 *
 * Like a task's, it stays readable once the list is deleted, and a list
 * changed a moment ago may have no rows yet: projection lags the write.
 */
export function useTaskListHistory(
  listId: string,
  filters: HistoryFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: taskListHistoryKeys.list(listId, filters.page, filters.limit),
    queryFn: () =>
      fetchTaskListHistory(listId, {
        page: filters.page,
        limit: filters.limit,
      }),
    enabled: options.enabled !== false && !!listId,
    staleTime: 2 * 60 * 1000, // 2 minutes for history
  });
}

/** Creates a list at the bottom of the user's lists. */
export function useCreateTaskList() {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationFn: createTaskList,
    onSuccess: async answer => {
      await storeList(queryClient, answer);
      void invalidateAfterMutation(queryClient, {
        queryKey: taskListKeys.listings(),
      });
      toast.success(SUCCESS_MESSAGES.TASK_LIST_CREATED);
    },
    onError: reportFailure,
  });
}

/** Renames a list, sets or clears its icon, or both. */
export function useUpdateTaskList() {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationFn: updateTaskList,
    ...listWriteCallbacks<TaskListUpdateInput>(
      queryClient,
      ({ listId }) => listId,
      SUCCESS_MESSAGES.TASK_LIST_UPDATED
    ),
  });
}

/** Archives a list: hidden from the active lists, read-only until unarchived. */
export function useArchiveTaskList() {
  return useSetArchived(true, SUCCESS_MESSAGES.TASK_LIST_ARCHIVED);
}

/** Unarchives a list: back among the active lists in its old place. */
export function useUnarchiveTaskList() {
  return useSetArchived(false, SUCCESS_MESSAGES.TASK_LIST_UNARCHIVED);
}

function useSetArchived(archived: boolean, wording: string) {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationFn: (listId: string) => setArchived(listId, archived),
    ...listWriteCallbacks<string>(queryClient, listId => listId, wording),
  });
}

/**
 * Deletes a list permanently — for mistakes; archiving is the ordinary
 * retirement. Its tasks go with it, except those holding both a creating and a
 * due journal, which stay as journal-only tasks.
 *
 * A 409 `TASK_LIST_ARCHIVED` (unarchive first) or `TASK_LIST_CHANGED` (re-read
 * and retry) arrives on the error's `code` for the caller to answer.
 */
export function useDeleteTaskList() {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationFn: deleteTaskList,
    // Taking part in the list's write sequence supersedes any write still out
    // on it: a rename that committed first but answers after the delete is no
    // longer the newest, so its answer cannot recreate the deleted detail.
    onMutate: (listId: string) => ({
      ticket: startMove(queryClient, listWriteScope(listId), false),
    }),
    onSuccess: (_, listId) => {
      // Removed rather than invalidated: a refetch would only answer 404, and
      // leaving them would let a later mount render a deleted list from cache.
      queryClient.removeQueries({ queryKey: taskListKeys.detail(listId) });
      queryClient.removeQueries({ queryKey: taskKeys.onList(listId) });
      void invalidateAfterMutation(
        queryClient,
        ...listChangeFilters(listId),
        // Kept tasks gain a membership row; deleted ones leave their journals'
        // due counts.
        { queryKey: taskHistoryKeys.all },
        { queryKey: journalKeys.lists() }
      );
      toast.success(SUCCESS_MESSAGES.TASK_LIST_DELETED);
    },
    onError: reportFailure,
    onSettled: (_answer, _error, listId) => {
      settleListWrite(queryClient, listId);
    },
  });
}

/** Re-orders the cached active listing by an order, keeping each list's own row. */
function orderActiveListing(
  queryClient: QueryClient,
  ids: readonly string[]
): boolean {
  let matched = true;
  queryClient.setQueryData<TaskListsResponse>(ACTIVE_LISTING, cached => {
    if (!cached) return cached;
    const ordered = orderByIds(cached.data, ids);
    matched = ordered.matched;
    return { ...cached, data: ordered.items };
  });
  return matched;
}

/** The cached order every list move writes to. */
const MOVE_SCOPE = 'task-lists:active';

/**
 * Takes a move's answer into the cached active listing: its order and each
 * list's new `position`, and nothing else. The rest of each cached row stays
 * as it is, because a rename or icon change may have landed while the move
 * was out, and the move's answer predates it.
 */
function applyMoveAnswer(
  queryClient: QueryClient,
  answer: TaskListMoveResponse
): boolean {
  const positions = new Map(
    answer.data.map(entry => [entry.id, entry.attributes.position])
  );
  const matched = orderActiveListing(
    queryClient,
    answer.data.map(entry => entry.id)
  );
  queryClient.setQueryData<TaskListsResponse>(ACTIVE_LISTING, cached =>
    cached
      ? {
          ...cached,
          data: cached.data.map(entry => {
            const position = positions.get(entry.id);
            return position === undefined
              ? entry
              : { ...entry, attributes: { ...entry.attributes, position } };
          }),
        }
      : cached
  );
  return matched;
}

/**
 * Moves a list to a new place among the **active** lists — the sidebar's and
 * the overview's drag, and its keyboard equivalent.
 *
 * - **Optimistic.** The list moves in the cached listing at once, so a drop
 *   never snaps back while it waits.
 * - **The answer is the new order, not a refetch** (ITER21-001 Phase 5): it is
 *   every active list in place, without counts, so the cached rows are
 *   re-sorted by it and keep their `open_task_count`.
 * - **Overlapping moves settle together.** Nothing is decided until the last
 *   pending move settles. If that one succeeded *and* is the newest, its
 *   answer is the whole truth and is taken. Otherwise — a failure, or an older
 *   move settling after a newer one — the listing is re-read: each move's
 *   snapshot may hold another's unconfirmed order, so no snapshot can be
 *   trusted to restore. A lone failed move puts its order back at once before
 *   the re-read lands.
 * - The listing is re-read too when the answer names other lists than the
 *   cache (one created elsewhere), or when a move cancelled a refresh that was
 *   already in flight.
 * - Every other listing in the manual order is re-read: `all`, and the
 *   name-filtered `active` and `all` listings, whose order and `position`s the
 *   move changed. The archived listings are ordered by when lists were
 *   archived, so they are left alone.
 */
export function useMoveTaskList() {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationKey: TASK_LIST_MOVE_KEY,
    mutationFn: moveTaskList,
    onMutate: async ({ listId, index }) => {
      const ticket = startMove(
        queryClient,
        MOVE_SCOPE,
        queryClient.getQueryState(ACTIVE_LISTING)?.fetchStatus === 'fetching'
      );
      await queryClient.cancelQueries({
        queryKey: ACTIVE_LISTING,
        exact: true,
      });
      const previous = queryClient
        .getQueryData<TaskListsResponse>(ACTIVE_LISTING)
        ?.data.map(entry => entry.id);

      queryClient.setQueryData<TaskListsResponse>(ACTIVE_LISTING, cached =>
        cached
          ? { ...cached, data: moveToIndex(cached.data, listId, index) }
          : cached
      );

      return { previous, ticket };
    },
    onError: reportFailure,
    onSettled: async (answer, error, _variables, context) => {
      // Any other pending move will settle later and decide for both.
      if (!settleMove(queryClient, MOVE_SCOPE)) return;

      const newest =
        context !== undefined &&
        isNewestMove(queryClient, MOVE_SCOPE, context.ticket);
      // Overlapping moves may have been applied in either order, so even the
      // newest answer is shown and then confirmed.
      let reread = takeRereadNeeded(queryClient, MOVE_SCOPE);
      if (await cancelReadInFlight(queryClient, ACTIVE_LISTING)) reread = true;

      if (!error && answer && newest) {
        reread = !applyMoveAnswer(queryClient, answer) || reread;
      } else {
        if (error && newest && context?.previous) {
          orderActiveListing(queryClient, context.previous);
        }
        reread = true;
      }

      void invalidateAfterMutation(
        queryClient,
        { queryKey: taskListKeys.listing({ archived: 'all' }) },
        { queryKey: taskListKeys.details() },
        { queryKey: taskListKeys.listings(), predicate: isNamedActiveListing },
        ...(reread ? [{ queryKey: ACTIVE_LISTING }] : [])
      );
    },
  });
}
