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
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import { statusChangeWording } from '@/lib/task-display';
import { invalidateAfterMutation } from './invalidate-after-mutation';

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

/** A change to a task's own state: everything that shows it can be stale. */
function refreshTask(queryClient: QueryClient, taskId: string): Promise<void> {
  return invalidateAfterMutation(
    queryClient,
    { queryKey: taskKeys.detail(taskId) },
    { queryKey: taskKeys.journalLists() },
    { queryKey: taskKeys.upcoming() }
  );
}

/**
 * A task appearing or disappearing.
 *
 * No detail key: a task being created has no id to have cached anything under,
 * and a deleted one's detail is *dropped* rather than invalidated — see
 * `forgetTask`.
 */
function refreshTaskCollections(queryClient: QueryClient): Promise<void> {
  return invalidateAfterMutation(
    queryClient,
    { queryKey: taskKeys.journalLists() },
    { queryKey: taskKeys.upcoming() }
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

/**
 * Task mutations do not retry.
 *
 * The app-wide default (`lib/providers.tsx`) retries a failed mutation once
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

// What is being written to a task right now
//
// Read from the mutation cache rather than from a hook instance, because a
// surface can mount the *same* task more than once. A journal renders a task
// holding two roles under both of its headings, so two rows carry two
// independent `useUpdateTask`s for one commitment; a guard that only knows its
// own instance leaves the twin live, and a second click races the first write
// with the server's ordering deciding which move survives.

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
    ...NO_RETRY,
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
    ...NO_RETRY,
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

      return { previous };
    },
    onError: (error: Error, { taskId }, context) => {
      context?.previous.forEach(([queryKey, attributes]) => {
        queryClient.setQueryData<CachedTaskPayload>(queryKey, cached =>
          patchCachedTask(cached, taskId, attributes)
        );
      });
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
      void refreshTask(queryClient, taskId);
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
    ...NO_RETRY,
    mutationFn: retargetTask,
    onSuccess: (_, { taskId }) => {
      void refreshTask(queryClient, taskId);
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
    ...NO_RETRY,
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
    ...NO_RETRY,
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
    ...NO_RETRY,
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
    ...NO_RETRY,
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
    ...NO_RETRY,
    mutationFn: detachTaskIntermediateJournal,
    onSuccess: (_, { taskId }) => {
      void refreshTaskJournalLinks(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_JOURNAL_DETACHED);
    },
    onError: reportFailure,
  });
}
