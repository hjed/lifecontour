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

import { LapseReason, TaskStatus } from '@/types/tasks';

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
