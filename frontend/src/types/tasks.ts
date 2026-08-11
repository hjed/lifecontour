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

/**
 * A task's status. Values must match the backend `TaskStatus` enum.
 *
 * Done is reversible through a `PATCH`. Cancelled is not: a cancelled task is
 * reopened by retargeting it onto a new future journal, which returns it to
 * `NOT_DONE`.
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
  /** The journal the commitment arose in; never changes. */
  creating_journal_id: number;
  /** The journal it is due in; may be retargeted. */
  due_journal_id: number;
  /** Journals it has passed through, oldest link first. Neither anchor appears. */
  intermediate_journal_ids: number[];
  created_at?: string | null;
  updated_at?: string | null;
}

/** A task as a read surface returns it: the written shape, resolved. */
export interface TaskReadAttributes extends TaskAttributes {
  creating_journal: TaskJournalRef;
  due_journal: TaskJournalRef;
  /** Same order and membership as `intermediate_journal_ids`, resolved. */
  intermediate_journals: TaskJournalRef[];
  contacts: TaskContactRef[];
  /**
   * Still not done, and the due journal has either passed or been cancelled.
   * Derived on every read and never stored.
   */
  lapsed: boolean;
  lapse_reason?: LapseReason | null;
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

/** Creating a task in the journal it arose from, which the path names. */
export interface TaskCreateInput {
  /** The creating journal — the one being viewed. Never chosen separately. */
  journalId: string;
  text: string;
  /** An existing future-dated journal of the user's. Never a bare date. */
  due_journal_id: number;
  contact_ids?: number[];
}

/**
 * Changing a task's text, its status, or both.
 *
 * A union rather than two optional fields, because the backend refuses a body
 * naming *neither* and that refusal should not be reachable from typed code:
 * `{ taskId }` alone would compile, send `attributes: {}` and come back a 400.
 * Each arm requires one attribute and leaves the other optional, so all three
 * legitimate shapes type-check and the empty one does not.
 */
export type TaskUpdateInput = { taskId: string } & (
  { text: string; status?: TaskStatus } | { status: TaskStatus; text?: string }
);

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
