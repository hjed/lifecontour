/**
 * How a task's backend enums are worded on a surface.
 *
 * The backend deliberately ships `LapseReason` as structured data rather than a
 * pre-worded string, "so surfaces can word it differently" — which makes the
 * wording a frontend concern, and this module the one place it is decided.
 *
 * Kept out of the components because the wording carries a product rule the
 * specification states outright: a journal must make it obvious that a task
 * lapsed because its due journal was **cancelled** rather than because the date
 * merely went by. The two must therefore stay distinguishable, and a pure
 * function is what lets a test assert that without rendering anything.
 */

import { LapseReason, TaskLinkRole, TaskStatus } from '@/types/tasks';

/** The two parts of a lapse marker: what it reads, and what it explains. */
export interface LapseMarker {
  /** The marker's visible text — and so its accessible name. */
  readonly label: string;
  /** A fuller sentence, carried as the marker's accessible description. */
  readonly description: string;
}

const LAPSE_MARKERS: Record<LapseReason, LapseMarker> = {
  [LapseReason.DATE_PASSED]: {
    label: 'Lapsed · date passed',
    description: "Lapsed: the date of this task's due journal has passed.",
  },
  [LapseReason.DUE_JOURNAL_CANCELLED]: {
    label: 'Lapsed · journal cancelled',
    description: "Lapsed: this task's due journal was cancelled.",
  },
};

/**
 * A lapse marker that names neither cause.
 *
 * Reachable only if a read model reports `lapsed` without a reason, which the
 * backend does not do. Worded as something true of both causes rather than as
 * an error, because a task that really has lapsed should still say so.
 */
const UNSPECIFIED_LAPSE: LapseMarker = {
  label: 'Lapsed',
  description:
    'Lapsed: it is still not done and its due journal is no longer ahead of it.',
};

/** Word a task's lapse, naming which of the two reasons applies. */
export function lapseWording(
  reason: LapseReason | null | undefined
): LapseMarker {
  return reason
    ? (LAPSE_MARKERS[reason] ?? UNSPECIFIED_LAPSE)
    : UNSPECIFIED_LAPSE;
}

const STATUS_WORDS: Record<TaskStatus, string> = {
  [TaskStatus.NOT_DONE]: 'Not done',
  [TaskStatus.DONE]: 'Done',
  [TaskStatus.CANCELLED]: 'Cancelled',
};

/** Word a task's status. Every status is shown; none is left implicit. */
export function statusWording(status: TaskStatus): string {
  return STATUS_WORDS[status] ?? status;
}

/** One inline status action a row can offer (**W24**). */
export interface TaskStatusAction {
  /** Stable identity for React keys, test ids and the offer table itself. */
  readonly key: 'done' | 'not-done' | 'cancel';
  /** The status the action moves the task to. */
  readonly target: TaskStatus;
  /** The visible button text. Short, as W24 draws it. */
  readonly label: string;
  /**
   * The button's accessible name.
   *
   * Longer than the label because "Done" and "Cancel" say what a control *is*
   * rather than what pressing it does, and it **contains** the visible label so
   * a user speaking what they can see still addresses it (WCAG 2.5.3).
   */
  readonly accessibleName: string;
}

const MARK_DONE: TaskStatusAction = {
  key: 'done',
  target: TaskStatus.DONE,
  label: 'Done',
  accessibleName: 'Mark done',
};

const RETURN_TO_NOT_DONE: TaskStatusAction = {
  key: 'not-done',
  target: TaskStatus.NOT_DONE,
  label: 'Not done',
  accessibleName: 'Return to not done',
};

const CANCEL: TaskStatusAction = {
  key: 'cancel',
  target: TaskStatus.CANCELLED,
  label: 'Cancel',
  accessibleName: 'Cancel task',
};

/**
 * What a row offers for a task in this status.
 *
 * **A cancelled task offers nothing here**, and that is the rule this table
 * exists to state. The service gives cancelled exactly one exit — retargeting
 * onto a new future journal, which revalidates the future-dated rule and always
 * lands on *not done* — and refuses `cancelled → done` and `cancelled → not
 * done` alike. A button for either could do nothing but draw a 409, so the
 * resurrect affordance belongs to the retarget dialog rather than here.
 *
 * A **lapsed** task is still not done, so it keeps the full not-done offer:
 * lapsing is a marker on a live commitment, never a disabled state.
 */
const STATUS_ACTIONS: Record<TaskStatus, readonly TaskStatusAction[]> = {
  [TaskStatus.NOT_DONE]: [MARK_DONE, CANCEL],
  [TaskStatus.DONE]: [RETURN_TO_NOT_DONE, CANCEL],
  [TaskStatus.CANCELLED]: [],
};

/** The inline status actions a task in this status offers, in display order. */
export function statusActions(status: TaskStatus): readonly TaskStatusAction[] {
  return STATUS_ACTIONS[status] ?? [];
}

/**
 * What a completed status change is reported to have done.
 *
 * The generic "Task updated successfully" does not say *what* changed, and the
 * toast is where the result is announced — Sonner's `Toaster` is a polite live
 * region, so this string is what a screen reader hears after the click.
 */
const STATUS_CHANGE_WORDS: Record<TaskStatus, string> = {
  [TaskStatus.NOT_DONE]: 'Task returned to not done',
  [TaskStatus.DONE]: 'Task marked done',
  [TaskStatus.CANCELLED]: 'Task cancelled',
};

/** Word the outcome of a status change, naming which outcome it was. */
export function statusChangeWording(status: TaskStatus): string {
  return STATUS_CHANGE_WORDS[status] ?? 'Task updated';
}

/**
 * The retarget affordance a row offers, worded for the task it acts on.
 *
 * A retarget is one call to one endpoint, but it is four different things to
 * ask for, and the specification treats them as different acts: extending a
 * deadline, bringing a *lapsed* commitment back, bringing a *cancelled* one
 * back — its only exit — and reopening one that was already finished. The
 * button, the dialog's heading and its explanation all have to say which.
 *
 * Deliberately **not** part of {@link statusActions}. That table is the status
 * transitions a row offers, and retargeting is not one: it writes a journal
 * link, forces the status to *not done* whatever it was, and is refused on
 * grounds the status matrix knows nothing about.
 */
export interface TaskRetargetOffer {
  /** Stable identity for React keys, test ids and the offer table itself. */
  readonly key: 'retarget';
  /** The visible button text. */
  readonly label: string;
  /**
   * The button's accessible name. **Contains** the visible label, so a user
   * speaking what they can see still addresses it (WCAG 2.5.3).
   */
  readonly accessibleName: string;
  /** The dialog's heading. */
  readonly dialogTitle: string;
  /** The dialog's explanation, which is where the reopen warning lives. */
  readonly dialogDescription: string;
  /** The dialog's confirm button. */
  readonly submitLabel: string;
}

const RESURRECT_LAPSED: TaskRetargetOffer = {
  key: 'retarget',
  label: 'Resurrect',
  accessibleName: 'Resurrect task onto a new due journal',
  dialogTitle: 'Resurrect this lapsed task',
  dialogDescription:
    'This task lapsed: it is still not done and its due journal is no longer ahead of it. Choose a future journal to make it due in, and it returns to the dashboard in due course.',
  submitLabel: 'Resurrect task',
};

const RESURRECT_CANCELLED: TaskRetargetOffer = {
  key: 'retarget',
  label: 'Resurrect',
  accessibleName: 'Resurrect task onto a new due journal',
  dialogTitle: 'Resurrect this cancelled task',
  dialogDescription:
    'Giving a cancelled task a new future journal to be due in is the way it comes back, and it returns as not done. Nothing else reopens it.',
  submitLabel: 'Resurrect task',
};

const RESCHEDULE: TaskRetargetOffer = {
  key: 'retarget',
  label: 'Reschedule',
  accessibleName: 'Reschedule task onto a new due journal',
  dialogTitle: 'Move this task to another journal',
  dialogDescription:
    'Choose the future journal this task should be due in. It stays not done, and the deadline moves with it.',
  submitLabel: 'Move task',
};

const REOPEN: TaskRetargetOffer = {
  key: 'retarget',
  label: 'Reopen',
  accessibleName: 'Reopen task onto a new due journal',
  dialogTitle: 'Reopen this completed task',
  dialogDescription:
    'This task is done. Moving it to another journal reopens it as not done — you will be asked to confirm that before anything is written.',
  submitLabel: 'Move task',
};

/**
 * How this task's retarget is offered and explained.
 *
 * A **cancelled** task answers regardless of `lapsed`: the read model never
 * reports a cancelled task as lapsed — a commitment called off cannot then be
 * let slide — but the caller passes both values straight through, so the
 * answer must not depend on that staying true.
 */
export function retargetAction(
  status: TaskStatus,
  lapsed: boolean
): TaskRetargetOffer {
  if (status === TaskStatus.CANCELLED) return RESURRECT_CANCELLED;
  if (status === TaskStatus.DONE) return REOPEN;
  return lapsed ? RESURRECT_LAPSED : RESCHEDULE;
}

/**
 * Whether a link in this role can be removed from the journal that carries it.
 *
 * The specification is explicit: "intermediate links can be removed. The
 * creating and due links cannot be removed, only replaced in the case of the
 * due journal." So this is a product rule rather than a rendering detail, and
 * it belongs beside the status offer table for the same reason that one does —
 * a table can be asserted exhaustively over the enum without rendering
 * anything, where an inline comparison in a component can only be asserted
 * through whichever rows a test happens to build.
 *
 * The rule is stated per **role**, not per task, because the listing renders a
 * task holding two roles in one journal **once per group**: a retarget onto a
 * journal the task already mentioned leaves it due *and* mentioned here, and
 * the intermediate link stays removable while the anchor does not. The
 * affordance therefore belongs to the row's group, and one commitment can show
 * a remove under *Mentioned* and none under *Due*.
 */
const REMOVABLE_LINK_ROLES: Record<TaskLinkRole, boolean> = {
  [TaskLinkRole.DUE]: false,
  [TaskLinkRole.CREATED]: false,
  [TaskLinkRole.MENTIONED]: true,
};

/** Whether a row in this link role offers to remove the link. */
export function linkRemovable(role: TaskLinkRole): boolean {
  return REMOVABLE_LINK_ROLES[role] ?? false;
}
