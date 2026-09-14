/**
 * Task API client functions using TanStack Query.
 *
 * Typed hooks over the task REST surface, following the journals client's
 * conventions: a query-key factory, module-level fetchers, sonner toasts and
 * `credentials: 'include'` on every call.
 *
 * Two things are deliberately different from the older clients in this
 * directory, and both are corrections rather than divergence:
 *
 * - **Failures throw `TaskApiError`, not a bare `Error`.** The older clients
 *   collapse a response to `errors[0].detail`, which discards the machine-
 *   readable `code` beside it. A task surface has to act on that code — a
 *   `TASK_REOPEN_NOT_ACKNOWLEDGED` is a confirmation to ask for, not a failure
 *   to report — so it is carried through rather than re-derived from prose.
 * - **Invalidation is not delayed behind a `setTimeout`.** The write commits in
 *   the service layer before the response is sent, so there is no
 *   read-after-write race to wait out; the journal-tag client (#1204) already
 *   dropped the timer and this follows it.
 *
 * There is no hook for the upcoming-window listing: that endpoint does not
 * exist yet. Its key namespace is reserved below so the dashboard's task
 * section and a journal's task list can be invalidated independently from the
 * outset.
 */

import {
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type QueryClient,
  type Mutation,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  JournalTasksResponse,
  LapseReason,
  TaskContactLinkInput,
  TaskCreateInput,
  TaskIntermediateJournalLinkInput,
  TaskLinkRole,
  TaskReadResponse,
  TaskResponse,
  TaskRetargetInput,
  TaskStatus,
  TaskUpdateInput,
} from '@/types/tasks';
import type { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
import type { HistoryFilters, HistoryListResponse } from '@/types/history';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import { statusChangeWording } from '@/lib/task-display';
import { invalidateAfterMutation } from './invalidate-after-mutation';
// From `./journal-keys`, never from `./journals`. This module is imported *by*
// the journal client, so reaching back into it would close a runtime cycle that
// breaks partial-mock tests — see the header of `journal-keys.ts`.
import { journalKeys } from './journal-keys';
// Safe to import whole, unlike the journal client above: `home-dashboard.ts`
// is a leaf — it imports the shared types and constants and nothing from this
// layer — so there is no cycle to close.
import { DashboardSectionStatus, homeDashboardKeys } from './home-dashboard';
import type {
  HomeDashboardResponse,
  HomeDashboardTask,
} from './home-dashboard';

/**
 * The refusal a *done* task's retarget draws when the reopen was not confirmed.
 *
 * Exported because it is not a failure: it is the service asking whether the
 * user meant to reopen a completed task, and a surface answers it with a
 * confirmation rather than an error message.
 */
export const TASK_REOPEN_NOT_ACKNOWLEDGED = 'TASK_REOPEN_NOT_ACKNOWLEDGED';

/**
 * The refusal a due journal draws when it is not dated after today.
 *
 * Exported for the same reason as the acknowledgement, one step further on:
 * this one belongs *against the due-journal field*, because it names the
 * choice the user just made. The toast it also raises is left in place — a
 * user who has scrolled away from the field would otherwise get no report at
 * all — so branching on it adds an inline message rather than replacing one.
 */
export const TASK_DUE_JOURNAL_NOT_FUTURE = 'TASK_DUE_JOURNAL_NOT_FUTURE';

/**
 * The refusal a journal draws when it already holds an **anchor** role on the
 * task — its creating journal, or its due journal.
 *
 * The two anchors are reachable only through `create_task` and
 * `retarget_due_journal`, so the intermediate relationship refuses to touch a
 * journal holding one. Exported for the same reason as the future-date refusal
 * above: the attach picker already excludes such a task, but it computes that
 * from a cache which can be stale — a task retargeted onto this journal from
 * somewhere else is an anchor here by the time the request lands — so the
 * answer belongs *against the field* the user chose in, not only in a toast.
 */
export const TASK_JOURNAL_IS_ANCHOR = 'TASK_JOURNAL_IS_ANCHOR';

/**
 * The domain's refusal of a field's *value* — empty text, a missing anchor.
 *
 * Unlike the three above, this one code covers several fields, so a surface
 * cannot decide where to put it from the code alone. `taskValidationField`
 * below reads the field out of the error's `meta`.
 */
export const TASK_VALIDATION_ERROR = 'TASK_VALIDATION_ERROR';

/**
 * The refusal a contact draws when it does not exist or is not the user's.
 *
 * Reachable from a create carrying contacts, where it belongs against the
 * contact field: a contact deleted in another tab is still in this form's
 * chosen list until the request comes back saying so.
 */
export const CONTACT_NOT_FOUND = 'CONTACT_NOT_FOUND';

/**
 * Which field a `TASK_VALIDATION_ERROR` is about, or `null` for anything else.
 *
 * The name is in the message too — every one of these reads `"{field}: ..."` —
 * but a form deciding which input to mark from an English prefix breaks
 * silently the first time the wording changes, so the backend sends it as
 * `meta.field` and this reads it from there. `null` rather than a guess when
 * the error is a different one, or carries no meta: a caller that cannot place
 * a refusal on a field should leave it to the toast rather than pick a field
 * at random.
 */
export function taskValidationField(error: unknown): string | null {
  if (!(error instanceof TaskApiError)) return null;
  if (error.code !== TASK_VALIDATION_ERROR) return null;

  const field = error.meta?.field;
  return typeof field === 'string' ? field : null;
}

/**
 * Query keys for tasks.
 *
 * `details`, `journalLists` and `upcoming` are **siblings** under `all`, never
 * nested one inside another, so invalidating a journal's task lists leaves the
 * dashboard's upcoming section untouched and vice versa. Phases 16–21 depend on
 * that independence; nesting one under the other would quietly remove it.
 */
export const taskKeys = {
  all: ['tasks'] as const,
  details: () => [...taskKeys.all, 'detail'] as const,
  detail: (taskId: string) => [...taskKeys.details(), taskId] as const,
  journalLists: () => [...taskKeys.all, 'journal'] as const,
  /**
   * One journal's tasks. The role is part of the key — a filtered listing
   * narrows `link_roles` as well as the rows, so it is a different answer and
   * not a subset of the unfiltered one.
   */
  journalList: (journalId: string, role?: TaskLinkRole) =>
    [...taskKeys.journalLists(), journalId, role ?? null] as const,
  /** Reserved for the dashboard's task section (ITER18-001 Phase 14). */
  upcoming: () => [...taskKeys.all, 'upcoming'] as const,
  upcomingWindow: (days: number) => [...taskKeys.upcoming(), days] as const,
};

/**
 * A task's change history, under a root of its **own** — not under `taskKeys`.
 *
 * `journalHistoryKeys` is `['journal-history']` rather than a branch of
 * `journalKeys`, and this follows it, because a history cache is not a cache of
 * the task: it holds `field_history` rows, whose `id` is a row id and whose
 * attributes have nothing in common with a task's.
 *
 * **Nesting it under `taskKeys.all` is actively wrong**, which is worth stating
 * because it is the arrangement that reads as tidy. `useUpdateTask.onMutate`
 * cancels and optimistically patches *every* query under `taskKeys.all`: a
 * history page underneath it would have its in-flight fetch cancelled by a
 * status click — leaving an open feed stuck on "No activity yet" with nothing
 * to refetch it — and `patchResource` matches on id alone, so a history row
 * whose id happened to equal the task's would have `status` and `text` merged
 * into it. Every journal and contact mutation invalidates `taskKeys.all` too
 * (see `task-cache-freshness.test.ts`), which would throw the history away for
 * a change that cannot affect it.
 */
export const taskHistoryKeys = {
  all: ['task-history'] as const,
  /**
   * Every page of one task's history — the key an invalidation names.
   *
   * `list(...)` is **not** usable as a filter: a query-key filter matches by
   * deep-partial equality, so `{ page: undefined, limit: undefined }` does not
   * match a mounted `{ page: 1, limit: 5 }`. Passing it to `invalidateQueries`
   * silently matches nothing and leaves the open disclosure stale for its whole
   * cache lifetime. Filters name this; only `useQuery` names `list`.
   */
  forTask: (taskId: string) => [...taskHistoryKeys.all, taskId] as const,
  list: (taskId: string, page?: number, limit?: number) =>
    [...taskHistoryKeys.forTask(taskId), { page, limit }] as const,
};

/**
 * A task request that the API refused, carrying what the refusal said.
 *
 * `code` is the backend's machine-readable error code — `TASK_NOT_FOUND`,
 * `TASK_DUE_JOURNAL_NOT_FUTURE`, `TASK_REOPEN_NOT_ACKNOWLEDGED` and the rest of
 * the map in `app/api/error_handlers.py` — and `meta` is the structured detail
 * the few refusals whose prose is not enough to act on attach. Both are absent
 * when the response carried no JSON:API error body at all.
 */
export class TaskApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly meta?: JsonApiMeta;

  constructor(
    message: string,
    status: number,
    code?: string,
    meta?: JsonApiMeta
  ) {
    super(message);
    this.name = 'TaskApiError';
    this.status = status;
    this.code = code;
    this.meta = meta;
  }
}

/**
 * Turns a failed response into the error the caller sees.
 *
 * The body is parsed defensively: a gateway error page, or anything else that
 * is not a JSON:API envelope, must still produce a usable message rather than a
 * `SyntaxError` from `response.json()` that says nothing about the request.
 */
async function toTaskApiError(
  response: Response,
  fallbackMessage: string
): Promise<TaskApiError> {
  let detail: string | undefined;
  let code: string | undefined;
  let meta: JsonApiMeta | undefined;

  try {
    const body = (await response.json()) as JsonApiErrorResponse;
    const error = body.errors?.[0];
    detail = error?.detail;
    code = error?.code;
    meta = error?.meta;
  } catch {
    // No body, or one that is not JSON. The status is all there is to go on.
  }

  return new TaskApiError(
    detail || fallbackMessage,
    response.status,
    code,
    meta
  );
}

/** Reads a JSON response, or throws what the failure said. */
async function readJson<T>(
  response: Response,
  fallbackMessage: string
): Promise<T> {
  if (!response.ok) {
    throw await toTaskApiError(response, fallbackMessage);
  }
  return response.json() as Promise<T>;
}

/**
 * Checks a response that answers 204.
 *
 * The body is never read: there is nothing in it, and calling `json()` on an
 * empty body throws.
 */
async function expectNoContent(
  response: Response,
  fallbackMessage: string
): Promise<void> {
  if (!response.ok) {
    throw await toTaskApiError(response, fallbackMessage);
  }
}

const JSON_HEADERS = { 'Content-Type': 'application/json' } as const;

// API Functions

async function fetchTask(taskId: string): Promise<TaskReadResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.BY_ID(taskId), {
    credentials: 'include',
  });

  return readJson<TaskReadResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function fetchTaskHistory(
  taskId: string,
  filters: HistoryFilters = {}
): Promise<HistoryListResponse> {
  const params = new URLSearchParams();

  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const response = await fetch(
    `${API_ENDPOINTS.TASKS.HISTORY(taskId)}?${params.toString()}`,
    { credentials: 'include' }
  );

  return readJson<HistoryListResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function fetchJournalTasks(
  journalId: string,
  role?: TaskLinkRole
): Promise<JournalTasksResponse> {
  const base = API_ENDPOINTS.TASKS.FOR_JOURNAL(journalId);
  const url = role ? `${base}?role=${role}` : base;

  const response = await fetch(url, { credentials: 'include' });

  return readJson<JournalTasksResponse>(response, ERROR_MESSAGES.FETCH_FAILED);
}

async function createTask({
  journalId,
  text,
  due_journal_id,
  contact_ids,
}: TaskCreateInput): Promise<TaskResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.FOR_JOURNAL(journalId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'tasks',
        attributes: {
          text,
          due_journal_id,
          // Omitted rather than sent as null or as `[]`: the attributes forbid
          // extras, and "no contacts" is the absence of the field. A picker
          // that yields an empty selection means the same thing as one that was
          // never opened, so both send the same body.
          ...(contact_ids?.length ? { contact_ids } : {}),
        },
      },
    }),
  });

  return readJson<TaskResponse>(response, ERROR_MESSAGES.CREATE_FAILED);
}

async function updateTask({
  taskId,
  text,
  status,
}: TaskUpdateInput): Promise<TaskResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.BY_ID(taskId), {
    method: 'PATCH',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        type: 'tasks',
        // JSON:API identifies the resource in the body as well as the path, and
        // the backend refuses a body whose id disagrees with the path.
        id: taskId,
        // Only what changed: the backend reads an absent attribute as "leave it
        // alone", so sending an explicit null would be a fourth state.
        attributes: {
          ...(text !== undefined ? { text } : {}),
          ...(status !== undefined ? { status } : {}),
        },
      },
    }),
  });

  return readJson<TaskResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function retargetTask({
  taskId,
  due_journal_id,
  acknowledge_reopen = false,
}: TaskRetargetInput): Promise<TaskResponse> {
  const response = await fetch(API_ENDPOINTS.TASKS.RETARGET(taskId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: JSON.stringify({
      data: {
        // The operation, named the way `journal-merge` is: a retarget is an
        // instruction with its own preconditions, not a task's attributes.
        type: 'task-retarget',
        attributes: {
          due_journal_id,
          // Always a JSON boolean. The backend's field is strict — 1, "true"
          // and "yes" are refused rather than coerced — because a confirmation
          // that can be produced by accident is not one.
          acknowledge_reopen,
        },
      },
    }),
  });

  return readJson<TaskResponse>(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function deleteTask(taskId: string): Promise<void> {
  const response = await fetch(API_ENDPOINTS.TASKS.BY_ID(taskId), {
    method: 'DELETE',
    credentials: 'include',
  });

  await expectNoContent(response, ERROR_MESSAGES.DELETE_FAILED);
}

async function linkTaskContact({
  taskId,
  contactId,
}: TaskContactLinkInput): Promise<void> {
  const response = await fetch(API_ENDPOINTS.TASKS.CONTACTS(taskId), {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    // A resource identifier and nothing else: a task-contact link carries no
    // relationship type, no role and no attendance status.
    body: JSON.stringify({ data: { type: 'contacts', id: contactId } }),
  });

  await expectNoContent(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function unlinkTaskContact({
  taskId,
  contactId,
}: TaskContactLinkInput): Promise<void> {
  const response = await fetch(API_ENDPOINTS.TASKS.CONTACT(taskId, contactId), {
    method: 'DELETE',
    credentials: 'include',
  });

  await expectNoContent(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function attachTaskIntermediateJournal({
  taskId,
  journalId,
}: TaskIntermediateJournalLinkInput): Promise<void> {
  const response = await fetch(
    API_ENDPOINTS.TASKS.INTERMEDIATE_JOURNALS(taskId),
    {
      method: 'POST',
      credentials: 'include',
      headers: JSON_HEADERS,
      // The resource type is `journals` — that is what the id points at — while
      // the route names the role, because only the intermediate link is
      // attachable. The anchors are set on creation and by retargeting.
      body: JSON.stringify({ data: { type: 'journals', id: journalId } }),
    }
  );

  await expectNoContent(response, ERROR_MESSAGES.UPDATE_FAILED);
}

async function detachTaskIntermediateJournal({
  taskId,
  journalId,
}: TaskIntermediateJournalLinkInput): Promise<void> {
  const response = await fetch(
    API_ENDPOINTS.TASKS.INTERMEDIATE_JOURNAL(taskId, journalId),
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  await expectNoContent(response, ERROR_MESSAGES.UPDATE_FAILED);
}

// Cache refreshes
//
// Each mutation names the smallest set of namespaces its change can reach, and
// every one of them goes through `invalidateAfterMutation` so the fetches are
// cancelled before they are invalidated (#1203).

/**
 * A change to a task's own state: everything that shows it can be stale.
 *
 * The task's **history** is named here explicitly, which is the whole point of
 * keeping it under a root of its own: a change to this task genuinely does
 * make its history stale, and nothing else should be able to discard it by
 * accident. Projection is asynchronous, so the refetch this triggers may still
 * arrive before the new row does — the specification allows that brief delay —
 * but the alternative is a feed that stays two minutes out of date on the one
 * surface that just changed.
 */
function taskFilters(taskId: string) {
  return [
    { queryKey: taskKeys.detail(taskId) },
    { queryKey: taskKeys.journalLists() },
    { queryKey: taskKeys.upcoming() },
    { queryKey: taskHistoryKeys.forTask(taskId) },
    REFRESH_HOME_DASHBOARD,
  ];
}

/**
 * The home dashboard, whose tasks section is a read of this very task.
 *
 * Named here rather than only where the dashboard's own card lives, for the
 * reason `journalKeys.lists()` is: **a mutation names the namespaces its change
 * can reach**, and the section embeds a task's text, its due journal and its
 * contacts, and is filtered by its status. Until now *nothing* invalidated this
 * key on a task write, and with the app-wide five-minute `staleTime` that means
 * a user who ticks something off and comes back to the dashboard is served the
 * pre-mutation projection.
 *
 * Every task refresh carries it **except {@link refreshTaskJournalLinks}**: the
 * section lists tasks by their *due* journal and draws no intermediate ones, so
 * a mention link cannot change what it would answer. The same narrowness the
 * journal lists are named with, applied to the same rule.
 *
 * The dashboard's *summary* is deliberately not a second concern here. The
 * dashboard read regenerates nothing server-side (ITER18-004 Phase 2), and the
 * summary card reads today's summary only on a page load's first read, never
 * on a refetch like this one (ITER18-005 Phase 8) — so this refetch cannot
 * produce a summary the user did not ask for, which is the client half of the
 * contract ITER18-005 Phase 7 relies on. What it *can* do is report today's
 * summary stale, since the write invalidated it; the card holds the summary it
 * has already drawn, and the next load brings the refreshed one.
 */
const REFRESH_HOME_DASHBOARD = { queryKey: homeDashboardKeys.all };

function refreshTask(queryClient: QueryClient, taskId: string): Promise<void> {
  return invalidateAfterMutation(queryClient, ...taskFilters(taskId));
}

/**
 * A change that can move a journal's `tasks_due_count`, and so the badge the
 * journal *list* renders from it.
 *
 * This is the "names only the namespaces its change can reach" rule pointing
 * the same way `useUpdateJournal` already points at `taskKeys`: the journal
 * list's row now embeds a fact derived from tasks, so a task write reaches a
 * journal namespace and has to say so. Without it the list keeps the old badge
 * for the app-wide five-minute `staleTime` — a user who ticks a task done on a
 * journal and goes back to the list is told it is still waiting on one.
 *
 * **`lists()` is the reachable set exactly**, not `journalKeys.all`. Only the
 * list endpoint computes the count; search and a contact's journals leave it
 * null and render no badge, so invalidating those would refetch pages whose
 * answer cannot have changed. `lists()` covers the infinite lists too, since
 * their key is built from it.
 *
 * Kept apart from {@link refreshTask} rather than folded into it because two of
 * that function's callers — linking and unlinking a **contact** — cannot move a
 * count, and the rule is only worth stating if it is applied narrowly.
 *
 * It is expressed as `taskFilters` **plus one key** rather than as a second list
 * of four, and that is the merge of ITER18-001 Phase 21 with ITER18-003 Phase 9
 * recorded in code: those two phases each added a key to "what a task write
 * reaches", one to each of these functions, and a duplicated list is how the
 * next such addition lands in one and not the other. This very merge nearly
 * shipped that way — the task-history key auto-merged into `refreshTask` alone,
 * which is the half a *status change* does not call.
 */
function refreshTaskAndDueCounts(
  queryClient: QueryClient,
  taskId: string
): Promise<void> {
  return invalidateAfterMutation(queryClient, ...taskFilters(taskId), {
    queryKey: journalKeys.lists(),
  });
}

/**
 * A task appearing or disappearing.
 *
 * No detail key: a task being created has no id to have cached anything under,
 * and a deleted one's detail is *dropped* rather than invalidated — see
 * `forgetTask`.
 *
 * Always moves a journal's due count by one, so `journalKeys.lists()` is
 * unconditional here where {@link refreshTaskAndDueCounts} is the opt-in form.
 */
function refreshTaskCollections(queryClient: QueryClient): Promise<void> {
  return invalidateAfterMutation(
    queryClient,
    { queryKey: taskKeys.journalLists() },
    { queryKey: taskKeys.upcoming() },
    REFRESH_HOME_DASHBOARD,
    { queryKey: journalKeys.lists() }
  );
}

/**
 * A mention link changing.
 *
 * The upcoming window is deliberately left alone: it lists tasks by their *due*
 * journal, and an intermediate link cannot move a task in or out of a forward
 * date window.
 */
function refreshTaskJournalLinks(
  queryClient: QueryClient,
  taskId: string
): Promise<void> {
  return invalidateAfterMutation(
    queryClient,
    { queryKey: taskKeys.detail(taskId) },
    { queryKey: taskKeys.journalLists() }
  );
}

/**
 * Drops a deleted task's cached detail rather than invalidating it.
 *
 * Invalidation is the wrong tool for a row that no longer exists: it would mark
 * the entry stale and refetch it into a 404. Leaving it alone is worse still —
 * the app-wide `staleTime` keeps it fresh for five minutes and `gcTime` keeps it
 * resident for ten, so a `useTask` mounting after the delete would render the
 * deleted task from cache without issuing a request at all.
 */
function forgetTask(queryClient: QueryClient, taskId: string): void {
  queryClient.removeQueries({ queryKey: taskKeys.detail(taskId) });
}

function reportFailure(error: Error): void {
  toast.error(error.message);
}

// Optimistic status changes
//
// The journal's inline actions (**W24**) must read as done the instant they are
// pressed and read as they did before if the write fails, so `useUpdateTask`
// patches every cached copy of the task in `onMutate` and puts each snapshot
// back in `onError`. The idiom is `useDismissIncompleteOutdoorActivity`'s:
// cancel, snapshot, patch, restore, and invalidate through the helper once the
// write settles either way.

/** The attributes an optimistic patch may set on a cached task. */
interface OptimisticTaskPatch {
  status?: TaskStatus;
  text?: string;
  lapsed?: boolean;
  lapse_reason?: LapseReason | null;
}

/** A task resource as it sits in any cached payload, whatever else it carries. */
interface CachedTaskResource {
  readonly id: string;
  readonly attributes: object;
}

/**
 * A cached payload embedding task resources.
 *
 * Two shapes, because a task's attributes are *embedded* rather than pointed
 * at: the single-resource detail read, and the array-shaped journal listing and
 * upcoming window. Patching one and not the other would leave a namespace
 * showing the status the user just changed.
 */
interface CachedTaskPayload {
  readonly data: CachedTaskResource | readonly CachedTaskResource[];
}

/** What a status write changes about a task, beyond the status itself. */
function optimisticPatch({
  status,
  text,
}: {
  status?: TaskStatus;
  text?: string;
}): OptimisticTaskPatch {
  const patch: OptimisticTaskPatch = {};

  if (text !== undefined) patch.text = text;
  if (status !== undefined) {
    patch.status = status;
    // Lapse is derived from "still not done and the due journal is no longer
    // ahead of it", so a task that has just left *not done* cannot be lapsed
    // and its marker goes at once. The reverse is not knowable here — it needs
    // the day boundary in the user's timezone — so returning a task to not done
    // leaves the marker to the refetch that follows.
    if (status !== TaskStatus.NOT_DONE) {
      patch.lapsed = false;
      patch.lapse_reason = null;
    }
  }

  return patch;
}

function patchResource(
  resource: CachedTaskResource,
  taskId: string,
  patch: OptimisticTaskPatch
): CachedTaskResource {
  return resource.id === taskId
    ? { ...resource, attributes: { ...resource.attributes, ...patch } }
    : resource;
}

/** Applies a patch to whichever of the two cached shapes was handed over. */
function patchCachedTask(
  cached: CachedTaskPayload | undefined,
  taskId: string,
  patch: OptimisticTaskPatch
): CachedTaskPayload | undefined {
  if (!cached) return cached;

  const { data } = cached;

  if (Array.isArray(data)) {
    return {
      ...cached,
      data: data.map(resource => patchResource(resource, taskId, patch)),
    };
  }

  return {
    ...cached,
    data: patchResource(data as CachedTaskResource, taskId, patch),
  };
}

/** Finds one task inside a cached payload, whichever shape it is in. */
function findCachedTask(
  cached: CachedTaskPayload | undefined,
  taskId: string
): CachedTaskResource | undefined {
  if (!cached) return undefined;

  const { data } = cached;

  if (Array.isArray(data)) {
    return data.find(resource => resource.id === taskId);
  }

  const single = data as CachedTaskResource | undefined;
  return single?.id === taskId ? single : undefined;
}

/** The attributes an optimistic patch can overwrite, and so must restore. */
const PATCHABLE_FIELDS = ['status', 'text', 'lapsed', 'lapse_reason'] as const;

/** One cache entry, and what the patched task read as inside *that* entry. */
type TaskAttributeSnapshot = readonly [readonly unknown[], OptimisticTaskPatch];

/**
 * What one task read as, in each cache entry holding it, before the patch.
 *
 * Two properties, and the rollback needs both:
 *
 * - **Per task, not per entry.** Two rows ticked one after the other share a
 *   cache entry, so putting back a whole snapshot taken before the first write
 *   would undo the second — a row the user had just ticked reverting because an
 *   unrelated one failed, with nothing on screen connecting the two. Restoring
 *   by id cannot reach a task the failed write never touched.
 * - **Per entry, not one value for all of them.** The detail read and the
 *   journal listing are fetched independently and can legitimately disagree —
 *   one refetched a moment ago, the other still inside the five-minute
 *   `staleTime`. Capturing one entry's value and writing it into every entry
 *   would undo that divergence as well as the patch, replacing a fresher cached
 *   value with a staler one from whichever entry happened to be enumerated
 *   first.
 *
 * Only the fields a patch can set are carried, and only where the cached shape
 * actually has them: writing `lapsed: undefined` over a real value would be a
 * different kind of corruption from the one being undone.
 */
function snapshotTaskAttributes(
  queryClient: QueryClient,
  taskId: string
): readonly TaskAttributeSnapshot[] {
  const snapshots: TaskAttributeSnapshot[] = [];

  for (const [
    queryKey,
    cached,
  ] of queryClient.getQueriesData<CachedTaskPayload>({
    queryKey: taskKeys.all,
  })) {
    const resource = findCachedTask(cached, taskId);
    if (!resource) continue;

    const attributes = resource.attributes as Record<string, unknown>;
    const previous: Record<string, unknown> = {};
    for (const field of PATCHABLE_FIELDS) {
      if (field in attributes) previous[field] = attributes[field];
    }
    snapshots.push([queryKey, previous as OptimisticTaskPatch]);
  }

  return snapshots;
}

// The home dashboard's tasks section, which a status change empties a row out of
//
// A third cached shape, and one the machinery above cannot describe. The task
// resources it patches sit at `data` or `data[]`; the dashboard's rows are
// nested at `data.attributes.tasks.data.tasks`, beside a `total`, under a
// different query key. Branching `patchCachedTask` on that would make one
// function serve two unrelated contracts, so this is a pair of its own.
//
// The patch is a **removal** rather than a field write, because the section's
// entry condition is *not done*: a row leaving that status leaves the list. Its
// rows carry no `status` to change — Phase 13 left it off the wire deliberately,
// since it is a constant for everything the section can hold.

/** One removed row: which cache entry it came out of, and what it was. */
type RemovedDashboardTask = readonly [readonly unknown[], HomeDashboardTask];

/** The tasks a cached dashboard document is currently showing, if any. */
function dashboardTasksOf(
  document: HomeDashboardResponse | undefined
): HomeDashboardTask[] | undefined {
  const section = document?.data.attributes.tasks;
  if (section?.status !== DashboardSectionStatus.READY) return undefined;

  const rows = section.data?.tasks;
  return Array.isArray(rows) ? rows : undefined;
}

/**
 * A cached dashboard document with its tasks section replaced.
 *
 * `total` is set from the list's own length rather than adjusted by one,
 * because the wire says in terms that the two are equal — the server caps
 * nothing, so the whole window travels and `total` is simply what the
 * show-more displays. Everything else in the document is carried by reference,
 * so the other three sections keep their identity and do not re-render.
 */
function withDashboardTasks(
  document: HomeDashboardResponse,
  tasks: HomeDashboardTask[]
): HomeDashboardResponse {
  const section = document.data.attributes.tasks;

  return {
    ...document,
    data: {
      ...document.data,
      attributes: {
        ...document.data.attributes,
        tasks: {
          ...section,
          data: { ...section.data!, total: tasks.length, tasks },
        },
      },
    },
  };
}

/** Takes a task out of every cached dashboard, reporting what it removed. */
function removeTaskFromDashboards(
  queryClient: QueryClient,
  taskId: string
): readonly RemovedDashboardTask[] {
  const removed: RemovedDashboardTask[] = [];

  for (const [
    queryKey,
    cached,
  ] of queryClient.getQueriesData<HomeDashboardResponse>({
    queryKey: homeDashboardKeys.all,
  })) {
    const tasks = dashboardTasksOf(cached);
    if (!cached || !tasks) continue;

    const index = tasks.findIndex(task => String(task.task_id) === taskId);
    if (index === -1) continue;

    removed.push([queryKey, tasks[index] as HomeDashboardTask]);
    queryClient.setQueryData(
      queryKey,
      withDashboardTasks(
        cached,
        tasks.filter((_, position) => position !== index)
      )
    );
  }

  return removed;
}

/**
 * Where a restored row belongs, by the order the server sent the list in.
 *
 * **Not the index it was removed from**, which is the correction the PR review
 * found. Two rows ticked while both are in flight are each removed from a list
 * the other has already shortened, so the index each captured describes a
 * transient state; restore them in the other order and the list comes back
 * misordered, claiming to be soonest-first when it is not.
 *
 * The comparison is the section's own documented rule — *"soonest first, ties
 * broken by task id"* — read off the two fields every row carries. That is the
 * one place this client is entitled to know the order: the card still draws
 * what it is given and never re-sorts, and this only decides where a row the
 * user did not really remove goes back. `days_away` stands in for the due date
 * because it is a monotonic function of it within one window, and it is what
 * the payload publishes.
 */
function restoredRowIndex(
  tasks: readonly HomeDashboardTask[],
  task: HomeDashboardTask
): number {
  const after = tasks.findIndex(
    row =>
      row.days_away > task.days_away ||
      (row.days_away === task.days_away && row.task_id > task.task_id)
  );

  return after === -1 ? tasks.length : after;
}

/**
 * Puts one removed row back, where the server's order says it belongs.
 *
 * **Per task, never a snapshot of the whole list**, which is ITER18-001 Phase
 * 17's decision 2b in a new shape. Two rows ticked one after the other share a
 * cache entry, so restoring the array as it stood before the first write would
 * silently resurrect the second — a commitment the user had just ticked off
 * reappearing because an unrelated row failed, with nothing on screen
 * connecting the two. Re-inserting one row by id cannot reach a task the failed
 * write never touched.
 *
 * The position comes from {@link restoredRowIndex} rather than from where the
 * row was taken out, because the list may have moved under it in the meantime —
 * the same mistake in a second direction, and the one the PR review caught.
 *
 * A row already back — the refetch beat the rollback — is left alone rather
 * than duplicated.
 */
function restoreTasksToDashboards(
  queryClient: QueryClient,
  removed: readonly RemovedDashboardTask[]
): void {
  for (const [queryKey, task] of removed) {
    queryClient.setQueryData<HomeDashboardResponse>(queryKey, cached => {
      const tasks = dashboardTasksOf(cached);
      if (!cached || !tasks) return cached;
      if (tasks.some(row => row.task_id === task.task_id)) return cached;

      const restored = [...tasks];
      restored.splice(restoredRowIndex(tasks, task), 0, task);
      return withDashboardTasks(cached, restored);
    });
  }
}

/**
 * Does this status change take the task out of the dashboard's section?
 *
 * Done **and** cancelled, because both are absent from it for the same reason
 * and this hook is shared with the journal surface, where cancel is offered —
 * removing only on `done` would leave a mounted dashboard showing a commitment
 * the user had just cancelled elsewhere. The same predicate
 * {@link optimisticPatch} uses to clear the lapse marker, for the same reason:
 * *not done* is what the section and the marker are both about.
 *
 * The reverse is deliberately **not** done. Whether a task returned to not done
 * belongs in this window depends on its due journal's date in the user's
 * configured zone, which is not knowable here, so that row arrives with the
 * refetch.
 */
function leavesDashboardSection(status: TaskStatus | undefined): boolean {
  return status !== undefined && status !== TaskStatus.NOT_DONE;
}

/**
 * Is this the last task write still standing?
 *
 * React Query's own rule for overlapping mutations, and this surface needs it:
 * a refresh fired while another write is in flight refetches the section from a
 * server that has not processed that write yet, so the response **carries the
 * row the other write optimistically removed** and puts it back on screen. The
 * user ticks two things off, one settles, and the other reappears for as long
 * as its own request takes.
 *
 * `onSettled` runs while the settling mutation is still `pending`, so it counts
 * itself: `1` means nothing else is outstanding and this write owns the
 * refresh. The predicate is `mutatingTaskId`'s, so only *task* writes hold the
 * refresh back — an unrelated contact or journal mutation should not.
 *
 * Nothing is lost when a write skips: whichever settles last refetches, and it
 * refetches on the failure path too.
 */
function isLastTaskWrite(queryClient: QueryClient): boolean {
  return queryClient.isMutating({ predicate: isTaskWrite }) <= 1;
}

/**
 * Task mutations do not retry.
 *
 * The app-wide default (`lib/query-client-options.ts`) retries a failed mutation once
 * after a second, which is wrong for this surface twice over:
 *
 * - **Creating a task is not idempotent.** A `POST` that succeeded on the
 *   server but lost its response would be sent again, and the user would end up
 *   with the same commitment recorded twice.
 * - **A refusal here is often the answer, not a failure.**
 *   `TASK_REOPEN_NOT_ACKNOWLEDGED` is the service asking whether reopening a
 *   done task was intended. Retrying it delays the confirmation the caller
 *   should show by the retry delay and logs a second refusal for every one the
 *   user resolves.
 *
 * Reads keep the default retry: a `GET` is idempotent and a transient failure
 * there is worth riding out.
 */
const NO_RETRY = { retry: false } as const;

/**
 * The mutation key every task write carries, and the only thing that makes a
 * mutation a task write.
 *
 * A task write used to be recognised by the shape of its input — any bare
 * string counted as a task id — and a journal, tag or series deletion and a
 * daily-summary regeneration all pass a bare string too, so an unrelated write
 * could lock a task's actions and hold the dashboard's refreshes back (Augment
 * review on PR #1470). Keyed, the identity is the hook that started the write.
 */
export const TASK_WRITE_KEY = ['task-write'] as const;

/** Options every task write shares: no retry, and the task-write key. */
const TASK_WRITE = { ...NO_RETRY, mutationKey: TASK_WRITE_KEY } as const;

// What is being written to a task right now
//
// Read from the mutation cache rather than from a hook instance, because a
// surface can mount the *same* task more than once. A journal renders a task
// holding two roles under both of its headings, so two rows carry two
// independent `useUpdateTask`s for one commitment; a guard that only knows its
// own instance leaves the twin live, and a second click races the first write
// with the server's ordering deciding which move survives.

/**
 * Whether a mutation in the cache is a write against a task.
 *
 * The one answer {@link isLastTaskWrite} counts with, exported for the
 * dashboard's read of today's summary on load (ITER18-005 Phase 8), which holds
 * its dashboard read-back for exactly the writes whose optimistic removal that
 * read could undo — and for no other mutation.
 */
export function isTaskWrite(mutation: Mutation): boolean {
  // Keyed *and* acting on an existing task. A creation carries the key but no
  // task id: it changes nothing a status update's refresh covers, so counting it
  // made `isLastTaskWrite` skip that refresh while the creation was pending, and
  // leave it skipped if the creation then failed (Greptile review on PR #1470).
  return (
    mutation.options.mutationKey?.[0] === TASK_WRITE_KEY[0] &&
    mutatingTaskId(mutation.state.variables) !== undefined
  );
}

/** The task a pending mutation is acting on, whatever shape its input takes. */
function mutatingTaskId(variables: unknown): string | undefined {
  // `useDeleteTask` takes the bare id; every other task mutation takes an
  // object carrying it.
  if (typeof variables === 'string') return variables;

  if (variables && typeof variables === 'object' && 'taskId' in variables) {
    const { taskId } = variables as { taskId?: unknown };
    return typeof taskId === 'string' ? taskId : undefined;
  }

  return undefined;
}

/**
 * Whether any write against one task is in flight, wherever it was started.
 *
 * **A boolean about the task, not about a button.** The obvious richer answer —
 * which *action* is pending, so its own control can carry `aria-busy` — cannot
 * work on this surface: the optimistic patch rewrites the cached status before
 * the request settles, the listing rerenders, and the row comes back offering
 * the **new** status's actions. The control that was clicked no longer exists,
 * so a busy flag matched to it is false on everything still on screen. The
 * action group is what is busy, and the group is what says so.
 *
 * Scoped to the task rather than to the caller deliberately: a journal renders
 * a task holding two roles once per group, so one commitment has two of these
 * side by side and they must lock together. A retarget opened elsewhere on the
 * page is just as much a reason not to accept a status click.
 */
export function useTaskWriteInFlight(taskId: string): boolean {
  const pending = useMutationState({
    filters: {
      status: 'pending',
      predicate: mutation =>
        isTaskWrite(mutation) &&
        mutatingTaskId(mutation.state.variables) === taskId,
    },
    select: mutation => mutation.state.variables,
  });

  return pending.length > 0;
}

// Hooks

/**
 * Reads one task whole: its journals by role, its contacts and its lapse.
 *
 * A lapsed task is not invalid — it stays completable, editable, cancellable
 * and retargetable — so callers render `lapsed` and `lapse_reason` as a marker
 * rather than as a disabled state.
 */
export function useTask(taskId: string) {
  return useQuery({
    queryKey: taskKeys.detail(taskId),
    queryFn: () => fetchTask(taskId),
    enabled: !!taskId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Reads one task's change history, most recent first.
 *
 * Two things about this endpoint shape the hook, and both come from ITER18-003
 * Phase 8:
 *
 * - **It answers for a task `useTask` reports as not found.** A task is
 *   hard-deleted and keeps its history, so this is not a read that can be
 *   folded into the task's own query.
 * - **An empty answer is not a missing task.** Projection lags the write, so a
 *   task changed a moment ago legitimately has no rows yet. `staleTime`
 *   therefore matches the other history hooks rather than the task ones: the
 *   answer goes stale on a background process's schedule, not the user's.
 *
 * `options.enabled` exists only to match `useJournalHistory` and
 * `useContactHistory`, whose shape the shared feed's hook contract is written
 * against. It is **not** how a collapsed journal row avoids fetching: the row
 * does not mount the feed at all until it is opened.
 */
export function useTaskHistory(
  taskId: string,
  filters: HistoryFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: taskHistoryKeys.list(taskId, filters.page, filters.limit),
    queryFn: () =>
      fetchTaskHistory(taskId, {
        page: filters.page,
        limit: filters.limit,
      }),
    enabled: options.enabled !== false && !!taskId,
    staleTime: 2 * 60 * 1000, // 2 minutes for history
  });
}

/**
 * Lists a journal's tasks, grouped by the role each link holds.
 *
 * Every linked task is returned in every status — done, cancelled and lapsed
 * included — because a journal is where a lapsed task is meant to be found
 * again. The dashboard, not this listing, is the surface that hides them.
 */
export function useJournalTasks(
  journalId: string,
  options: { role?: TaskLinkRole } = {}
) {
  return useQuery({
    queryKey: taskKeys.journalList(journalId, options.role),
    queryFn: () => fetchJournalTasks(journalId, options.role),
    enabled: !!journalId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/** Creates a task in the journal it arose from, due in a future journal. */
export function useCreateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: createTask,
    onSuccess: () => {
      void refreshTaskCollections(queryClient);
      toast.success(SUCCESS_MESSAGES.TASK_CREATED);
    },
    onError: reportFailure,
  });
}

/**
 * Changes a task's text, its status, or both as a single request.
 *
 * Leaving *cancelled* is refused here — a cancelled task is reopened by
 * retargeting it onto a new future journal — and the refusal arrives as a 409
 * whose message says so.
 *
 * **The change is applied optimistically.** The journal's inline actions are a
 * tick-and-move-on affordance, so the row shows the new status before the
 * request has been answered, and every cached copy is put back if it fails.
 * The success toast is worded from what changed rather than from the generic
 * update message: Sonner's `Toaster` is a polite live region, so this string is
 * how the action announces its result.
 */
export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: updateTask,
    onMutate: async ({ taskId, status, text }) => {
      // Every namespace under `all`: the same attributes are embedded in the
      // detail read, the journal listings and the upcoming window alike.
      await queryClient.cancelQueries({ queryKey: taskKeys.all });

      const previous = snapshotTaskAttributes(queryClient, taskId);

      const patch = optimisticPatch({ status, text });
      queryClient.setQueriesData<CachedTaskPayload>(
        { queryKey: taskKeys.all },
        cached => patchCachedTask(cached, taskId, patch)
      );

      // A separate key and a separate shape, so a second cancel rather than a
      // wider filter — and only when the status change actually empties the
      // row out of the section, since nothing else here removes a row.
      let removed: readonly RemovedDashboardTask[] = [];
      if (leavesDashboardSection(status)) {
        await queryClient.cancelQueries({ queryKey: homeDashboardKeys.all });
        removed = removeTaskFromDashboards(queryClient, taskId);
      }

      return { previous, removed };
    },
    onError: (error: Error, { taskId }, context) => {
      context?.previous.forEach(([queryKey, attributes]) => {
        queryClient.setQueryData<CachedTaskPayload>(queryKey, cached =>
          patchCachedTask(cached, taskId, attributes)
        );
      });
      restoreTasksToDashboards(queryClient, context?.removed ?? []);
      reportFailure(error);
    },
    onSuccess: (_, { status }) => {
      toast.success(
        status ? statusChangeWording(status) : SUCCESS_MESSAGES.TASK_UPDATED
      );
    },
    // Settled rather than success: a failed write has just had its rollback
    // applied from a snapshot that may itself be stale, so the refetch is worth
    // as much on that path as on the happy one.
    onSettled: (_data, _error, { taskId }) => {
      // Only the last task write standing refetches — see `isLastTaskWrite`.
      // Refreshing while another is in flight would answer from a server that
      // has not processed it, undoing its optimistic removal on screen.
      if (!isLastTaskWrite(queryClient)) return;

      // The due counts go in the same call because a PATCH may carry a status,
      // and a status change is exactly what adds a commitment to a journal's
      // badge or takes it away. A text-only edit over-invalidates the journal
      // lists by one refetch; the hook cannot know which it was without reading
      // the variables back, and getting this wrong the other way leaves the
      // badge lying for five minutes.
      void refreshTaskAndDueCounts(queryClient, taskId);
    },
  });
}

/**
 * Moves a task onto a new due journal, keeping the one it is leaving.
 *
 * This is how a deadline is extended and the only way a cancelled or done task
 * is reopened. A done task's retarget is refused until `acknowledge_reopen`
 * says the reopen was intended — **which is not a failure**, so it raises no
 * toast: the caller answers it with a confirmation and retries.
 */
export function useRetargetTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: retargetTask,
    onSuccess: (_, { taskId }) => {
      // A retarget moves the count on **two** journals — one down, one up — and
      // both can be on the same page of the list.
      void refreshTaskAndDueCounts(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_RETARGETED);
    },
    onError: (error: Error) => {
      if (
        error instanceof TaskApiError &&
        error.code === TASK_REOPEN_NOT_ACKNOWLEDGED
      ) {
        return;
      }
      reportFailure(error);
    },
  });
}

/**
 * Deletes a task permanently.
 *
 * Cancelling is the ordinary action and this is the exception: a cancelled task
 * stays part of the record and can be reopened, a deleted one is gone.
 */
export function useDeleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: deleteTask,
    onSuccess: (_, taskId) => {
      forgetTask(queryClient, taskId);
      void refreshTaskCollections(queryClient);
      toast.success(SUCCESS_MESSAGES.TASK_DELETED);
    },
    onError: reportFailure,
  });
}

/** Links a contact to a task. Idempotent, and allowed in any status. */
export function useLinkTaskContact() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: linkTaskContact,
    onSuccess: (_, { taskId }) => {
      void refreshTask(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_CONTACT_LINKED);
    },
    onError: reportFailure,
  });
}

/** Removes a contact link from a task. Idempotent. */
export function useUnlinkTaskContact() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: unlinkTaskContact,
    onSuccess: (_, { taskId }) => {
      void refreshTask(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_CONTACT_UNLINKED);
    },
    onError: reportFailure,
  });
}

/**
 * Attaches a journal to a task as an intermediate ("mentioned") journal.
 *
 * Refused with a 409 when the journal is already the task's creating or due
 * journal: it is linked in a role this relationship cannot express.
 */
export function useAttachTaskIntermediateJournal() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: attachTaskIntermediateJournal,
    onSuccess: (_, { taskId }) => {
      void refreshTaskJournalLinks(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_JOURNAL_ATTACHED);
    },
    onError: reportFailure,
  });
}

/** Removes an intermediate-journal link from a task. */
export function useDetachTaskIntermediateJournal() {
  const queryClient = useQueryClient();

  return useMutation({
    ...TASK_WRITE,
    mutationFn: detachTaskIntermediateJournal,
    onSuccess: (_, { taskId }) => {
      void refreshTaskJournalLinks(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_JOURNAL_DETACHED);
    },
    onError: reportFailure,
  });
}
