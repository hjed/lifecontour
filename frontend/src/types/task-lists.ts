/**
 * Task-list types matching `backend/app/api/tasks/task_list_schemas.py`.
 *
 * A list is a user's named home for tasks. Its resource type is `task-lists`.
 * Two resource shapes exist because only the **listing** counts a list's open
 * tasks: reading one list, and every write answer, return the list alone, so a
 * single read is never stored where a listing entry is expected.
 */

import type { JsonApiLinks } from './api';
import type { HistoryPaginationMeta } from './history';
import type { TaskIcon } from './task-icons';

/** Which of a user's lists the listing answers. Values must match the backend `TaskListArchiveFilter`. */
export type TaskListArchiveFilter = 'active' | 'archived' | 'all';

/** A list as one read, a create, an update, an archive or an unarchive answers it. */
export interface TaskListAttributes {
  name: string;
  icon: TaskIcon | null;
  /**
   * The list's place among **all** the user's lists, archived ones included.
   * Not the index a move takes, which counts only the active lists.
   */
  position: number;
  archived: boolean;
  /** When it was first archived (ISO instant); `null` while active. */
  archived_at: string | null;
  /** The one journal the list is associated with; `null` when it has none. */
  associated_journal_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** A list as the listing answers it: the list, plus its not-done task count. */
export interface TaskListSummaryAttributes extends TaskListAttributes {
  open_task_count: number;
}

export interface TaskListResource {
  type: 'task-lists';
  id: string;
  attributes: TaskListAttributes;
  links?: JsonApiLinks | null;
}

export interface TaskListSummaryResource {
  type: 'task-lists';
  id: string;
  attributes: TaskListSummaryAttributes;
  links?: JsonApiLinks | null;
}

/** What one read and every list write answer with. */
export interface TaskListResponse {
  data: TaskListResource;
}

/** What `GET /api/task-lists` answers with when no page is asked for: every matching list. */
export interface TaskListsResponse {
  data: TaskListSummaryResource[];
}

/**
 * One page of `GET /api/task-lists`, asked for with `page` and `limit`. Page
 * by number from `meta`: the backend's `links` are absolute, built from its
 * own base URL.
 */
export interface TaskListsPageResponse {
  data: TaskListSummaryResource[];
  meta: HistoryPaginationMeta;
  links?: JsonApiLinks | null;
}

/**
 * What a list move answers with: the user's **active** lists in their new
 * order, without counts — one move renumbers several lists.
 */
export interface TaskListMoveResponse {
  data: TaskListResource[];
}

/**
 * The list a task is on, as a task read embeds it.
 *
 * `id` is a number here, as on the wire, where a resource id is a string.
 */
export interface TaskListRef {
  id: number;
  name: string;
  icon: TaskIcon | null;
  archived: boolean;
}

/** Creating a list. It always joins the bottom of the active lists. */
export interface TaskListCreateInput {
  name: string;
  icon?: TaskIcon;
}

/**
 * Renaming a list, setting or clearing its icon, or both.
 *
 * A union so that a body naming no change — which the backend refuses — does
 * not compile. `icon: null` clears the icon; an absent `icon` keeps it. A list
 * must have a name, so `name` is never nullable.
 */
export type TaskListUpdateInput = { listId: string } & (
  | { name: string; icon?: TaskIcon | null }
  | { icon: TaskIcon | null; name?: string }
);

/**
 * Moving a list among the **active** lists. `index` 0 is the top; an index
 * past the end puts it at the bottom.
 */
export interface TaskListMoveInput {
  listId: string;
  index: number;
}
