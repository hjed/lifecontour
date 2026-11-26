/**
 * Query keys for task lists and their history.
 *
 * A key root here is a resource type, as `contactKeys`, `journalKeys` and
 * `taskHistoryKeys` are, so a filter on a root is a statement about one kind of
 * payload. Lists therefore sit under `['task-lists']`, **not** under
 * `taskKeys.all`: that root is what every task write cancels and patches as
 * task resources, and what every journal, contact and timezone write
 * invalidates because those writes change embedded task data. A list is a
 * different aggregate — its own attributes and count, changed by its own
 * writes — and putting it there would have a status tick cancel the sidebar's
 * listing and a journal rename refetch every list. Where a list and its tasks
 * do depend on each other (a task write moves a list's `open_task_count`; a
 * list rename changes the `task_list` a task read embeds), the mutation names
 * the other root explicitly.
 *
 * A **list's tasks** are the exception that proves the rule: they are task
 * resources, so they live under `taskKeys` (`taskKeys.onLists()`).
 *
 * Kept in its own module so `tasks.ts` can name these keys without importing
 * the list hooks, which import from `tasks.ts`.
 */

import type { TaskListArchiveFilter } from '@/types/task-lists';

/** What the listing is asked for. An object, so later filters extend it. */
export interface TaskListListingParams {
  archived: TaskListArchiveFilter;
}

export const taskListKeys = {
  all: ['task-lists'] as const,
  /** Every listing, whatever its filter — the key an invalidation names. */
  listings: () => [...taskListKeys.all, 'listing'] as const,
  listing: (params: TaskListListingParams) =>
    [...taskListKeys.listings(), params] as const,
  details: () => [...taskListKeys.all, 'detail'] as const,
  detail: (listId: string) => [...taskListKeys.details(), listId] as const,
};

/**
 * A list's change history, under a root of its own for the reason
 * `taskHistoryKeys` gives: history rows are not lists, and their ids are row
 * ids. As there, `list(...)` is for `useQuery` only — a filter built from it
 * with an absent page or limit matches nothing — and invalidations name
 * `forList`.
 */
export const taskListHistoryKeys = {
  all: ['task-list-history'] as const,
  forList: (listId: string) => [...taskListHistoryKeys.all, listId] as const,
  list: (listId: string, page?: number, limit?: number) =>
    [...taskListHistoryKeys.forList(listId), { page, limit }] as const,
};
