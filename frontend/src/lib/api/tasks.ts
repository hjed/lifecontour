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
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  JournalTasksResponse,
  TaskContactLinkInput,
  TaskCreateInput,
  TaskIntermediateJournalLinkInput,
  TaskLinkRole,
  TaskReadResponse,
  TaskResponse,
  TaskRetargetInput,
  TaskUpdateInput,
} from '@/types/tasks';
import type { JsonApiErrorResponse, JsonApiMeta } from '@/types/api';
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
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
 */
export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    ...NO_RETRY,
    mutationFn: updateTask,
    onSuccess: (_, { taskId }) => {
      void refreshTask(queryClient, taskId);
      toast.success(SUCCESS_MESSAGES.TASK_UPDATED);
    },
    onError: reportFailure,
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
