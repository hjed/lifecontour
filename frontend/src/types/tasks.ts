/**
 * Task-related types matching backend API schemas.
 *
 * These mirror `backend/app/api/tasks/schemas.py`. The read shape is a strict
 * **superset** of the written one there — every attribute a create, a `PATCH`
 * or a retarget answers with is inherited by the read model, which adds the
 * resolved journals, the contacts and the lapse — so the interfaces below
 * extend rather than redeclare, and one renderer can take either.
 */

import { JsonApiLinks, JsonApiMeta } from './api';
import type { HistoryPaginationMeta } from './history';
import type { TaskIcon } from './task-icons';
import type { TaskListRef } from './task-lists';

/**
 * A task's status. Values must match the backend `TaskStatus` enum.
 *
 * Done is reversible through a `PATCH`. Cancelled is too for a task on a
 * list; a cancelled journal-only task is reopened only by retargeting it onto
 * a new future journal, which returns it to `NOT_DONE`.
 */
export enum TaskStatus {
  NOT_DONE = 'not_done',
  DONE = 'done',
  CANCELLED = 'cancelled',
}

/**
 * Why a task lapsed. Values must match the backend `LapseReason` enum.
 *
 * Structured rather than pre-worded, because the two ask the user for
 * different things: a day that went by invites retargeting, while a meeting
 * that was called off may mean the commitment is moot.
 */
export enum LapseReason {
  DATE_PASSED = 'date_passed',
  DUE_JOURNAL_CANCELLED = 'due_journal_cancelled',
}

/**
 * How a task is linked to a journal. Values must match the backend
 * `TaskLinkRole` enum.
 *
 * A task can hold more than one role in the same journal — the same journal
 * can be both its anchors, and retargeting onto a journal it already mentioned
 * leaves that mention in place.
 */
export enum TaskLinkRole {
  DUE = 'due',
  CREATED = 'created',
  MENTIONED = 'mentioned',
}

/** One of a task's journals, resolved enough to render a link. */
export interface TaskJournalRef {
  id: number;
  title: string;
  /**
   * An ISO date (`YYYY-MM-DD`), already resolved in the user's timezone — not
   * an instant. Re-deriving it in the browser's zone would let a surface
   * disagree with the rule that judged whether the task lapsed.
   */
  date: string;
  /**
   * Whether this is a cancelled event journal. Only the *due* journal's value
   * lapses a task, but the flag rides on every journal so a surface can mark
   * one wherever it shows it.
   */
  cancelled: boolean;
}

/** One of a task's contacts. A plain reference: no type, no role, no status. */
export interface TaskContactRef {
  id: number;
  display_name: string;
  photo_url?: string | null;
}

/** A task as a write response returns it. */
export interface TaskAttributes {
  text: string;
  status: TaskStatus;
  /**
   * The journal the commitment arose in; never changes. `null` for a task on
   * a list that arose in no journal — a task with no list always has one.
   */
  creating_journal_id: number | null;
  /**
   * The journal it is due in; may be retargeted. `null` for a task on a list
   * with no due journal (undated, or dated by a due date instead) — a task
   * with no list always has one.
   */
  due_journal_id: number | null;
  /** Journals it has passed through, oldest link first. Neither anchor appears. */
  intermediate_journal_ids: number[];
  /**
   * The list the task is on, or `null` for a journal-only task. A list task's
   * due journal is a plain date: moving it keeps the status.
   */
  task_list_id: number | null;
  /**
   * An ISO calendar date (`YYYY-MM-DD`) a list task is due on, or `null`. A
   * list task has at most one of this and a due journal.
   */
  due_date: string | null;
  /** "This one matters" — an on/off marker on every task, journal-only included. */
  flagged: boolean;
  /** A key from the fixed icon set, or `null` for no icon. */
  icon: TaskIcon | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** A task as a read surface returns it: the written shape, resolved. */
export interface TaskReadAttributes extends TaskAttributes {
  /** `creating_journal_id` resolved; `null` exactly when that is. */
  creating_journal: TaskJournalRef | null;
  /** `due_journal_id` resolved; `null` exactly when that is. */
  due_journal: TaskJournalRef | null;
  /** Same order and membership as `intermediate_journal_ids`, resolved. */
  intermediate_journals: TaskJournalRef[];
  /** `task_list_id` resolved; `null` exactly when that is. */
  task_list: TaskListRef | null;
  contacts: TaskContactRef[];
  /**
   * Still not done, and the due journal has either passed or been cancelled.
   * Derived on every read and never stored. Always `false` on a task on a
   * list: a list task never lapses.
   */
  lapsed: boolean;
  lapse_reason?: LapseReason | null;
  /**
   * A list task past its date and still not done — the list's counterpart of
   * `lapsed`, derived on every read by the same day rules (a multi-day due
   * journal counts only after its last day). Always `false` on a journal-only
   * task, which lapses instead.
   */
  overdue: boolean;
}

/**
 * A task as a *journal's* listing returns it: the read shape, plus its roles.
 *
 * `link_roles` exists only here — on a single-task read there is no journal in
 * question, so the field would be a question the payload cannot answer.
 */
export interface JournalTaskAttributes extends TaskReadAttributes {
  link_roles: TaskLinkRole[];
}

export interface TaskResource {
  type: string;
  id: string;
  attributes: TaskAttributes;
  links?: JsonApiLinks | null;
}

export interface TaskReadResource {
  type: string;
  id: string;
  attributes: TaskReadAttributes;
  links?: JsonApiLinks | null;
}

export interface JournalTaskResource {
  type: string;
  id: string;
  attributes: JournalTaskAttributes;
  links?: JsonApiLinks | null;
}

/** The journal's tasks by role, as ordered id lists. All three keys always present. */
export interface JournalTaskGroupIds {
  due: number[];
  created: number[];
  mentioned: number[];
}

export interface JournalTasksMeta extends JsonApiMeta {
  groups: JournalTaskGroupIds;
}

/** What create, `PATCH` and retarget answer with. */
export interface TaskResponse {
  data: TaskResource;
}

/** What `GET /api/tasks/{id}` answers with. */
export interface TaskReadResponse {
  data: TaskReadResource;
}

/**
 * What `GET /api/journals/{id}/tasks` answers with.
 *
 * Each task appears **once** in `data` however many of the journal's roles it
 * holds — JSON:API forbids the same resource twice there — so the roles ride on
 * each resource and the grouping lives in `meta.groups`. Unpaginated: a
 * journal's tasks are bounded by the journal, so there is no pagination `meta`.
 */
export interface JournalTasksResponse {
  data: JournalTaskResource[];
  meta: JournalTasksMeta;
}

/**
 * What `GET /api/task-lists/{id}/tasks` answers with: the list's **open**
 * tasks in the user's manual order, read whole. Unpaginated; `meta.total` is
 * the count.
 */
export interface ListTasksResponse {
  data: TaskReadResource[];
  meta: { total: number };
}

/**
 * What `GET /api/task-lists/{id}/tasks/completed` answers with: one page of
 * the list's done and cancelled tasks, most recently closed first.
 *
 * Page from `meta`, not from `links`: the backend builds `links` as absolute
 * URLs from its own base URL, which need not be the origin the browser talks
 * to, and sends `next: null` on the last page rather than leaving it out.
 */
export interface CompletedListTasksResponse {
  data: TaskReadResource[];
  meta: HistoryPaginationMeta;
  links?: JsonApiLinks | null;
}

/**
 * What a reorder answers with: the list's open tasks in their new order, in
 * the **write** shape — no journals, contacts or `overdue`. Its ids are the
 * order; its rows are not a substitute for the read models a list page holds.
 */
export interface TaskCollectionResponse {
  data: TaskResource[];
}

/** Creating a task in the journal it arose from, which the path names. */
export interface TaskCreateInput {
  /**
   * The creating journal: the one being viewed on a journal page, or the one
   * chosen in the New dialog. Sent in the path, never in the body.
   */
  journalId: string;
  text: string;
  /** An existing future-dated journal of the user's. Never a bare date. */
  due_journal_id: number;
  contact_ids?: number[];
}

/**
 * Creating a task at the bottom of one of the user's lists, in no journal.
 *
 * At most one date: a due date (`YYYY-MM-DD`, today or later) **or** a due
 * journal (dated in the future). The backend refuses both together, so the
 * union does too.
 */
export type ListTaskCreateInput = {
  /** The list, sent in the path. */
  listId: string;
  text: string;
  contact_ids?: number[];
} & (
  | { due_date?: string; due_journal_id?: never }
  | { due_journal_id?: number; due_date?: never }
);

/** Everything a task `PATCH` can change. `null` clears; absent keeps. */
interface TaskChanges {
  text: string;
  status: TaskStatus;
  /** A JSON boolean: the backend refuses `null`. */
  flagged: boolean;
  icon: TaskIcon | null;
  /** A list task's due day (`YYYY-MM-DD`), or `null` to make it undated. */
  due_date: string | null;
  /**
   * A list task's due journal, or `null` to clear it. On a journal-only task
   * this is a retarget, and cannot be cleared.
   */
  due_journal_id: number | null;
}

/** Exactly one of `TaskChanges` required, the rest optional. */
type OneChange = {
  [K in keyof TaskChanges]: Pick<TaskChanges, K> &
    Partial<Omit<TaskChanges, K>>;
}[keyof TaskChanges];

/**
 * Changing anything a task `PATCH` takes, in one write.
 *
 * A union, because the backend refuses a body naming no change and that
 * refusal should not be reachable from typed code: `{ taskId }` alone would
 * compile, send `attributes: {}` and come back a 400. Each arm requires one
 * change and leaves the others optional, so every legitimate shape
 * type-checks and the empty one does not. `acknowledge_reopen` confirms that
 * moving a *done* journal-only task onto a due journal reopens it — it is not
 * a change on its own.
 */
export type TaskUpdateInput = {
  taskId: string;
  acknowledge_reopen?: boolean;
} & OneChange &
  // A list task has a due date or a due journal, never both, and the backend
  // refuses a body setting the two together.
  ({ due_date?: never } | { due_journal_id?: never });

/**
 * Moving an open list task to the top (`afterTaskId: null`) or directly after
 * another open task on the same list.
 */
export interface ListTaskReorderInput {
  taskId: string;
  /** The list the task is on, whose cached open tasks are re-ordered. */
  listId: string;
  afterTaskId: string | null;
}

/** Putting a task on a list, or moving it to another. It joins the bottom. */
export interface TaskMoveInput {
  taskId: string;
  taskListId: string;
}

/** Moving a task onto a new due journal, which always leaves it not done. */
export interface TaskRetargetInput {
  taskId: string;
  due_journal_id: number;
  /**
   * Confirms that reopening a *done* task is intended. Without it the backend
   * refuses with `TASK_REOPEN_NOT_ACKNOWLEDGED` rather than reopening silently.
   * Ignored for any other status.
   */
  acknowledge_reopen?: boolean;
}

/** Linking or unlinking one of a task's contacts. */
export interface TaskContactLinkInput {
  taskId: string;
  contactId: string;
}

/** Attaching or detaching one of a task's intermediate journals. */
export interface TaskIntermediateJournalLinkInput {
  taskId: string;
  journalId: string;
}
