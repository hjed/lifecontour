/**
 * How a task's history entry reads, on each of the two feeds it can appear on.
 *
 * Pure functions rather than logic inside `ActivityItem`, for the reason
 * `lib/task-display.ts` gives about the lapse wording: what an entry *says* is
 * a product rule — the specification's *Where tasks appear* turns on the
 * contact entry reading as a record rather than an offer — and a pure function
 * is what lets a test assert it without rendering a component.
 *
 * Two properties are load-bearing.
 *
 * **It is gated on `entity_type`, not on the field name.** The marker
 * vocabulary is shared across domains: a journal writes `__created__`, and a
 * contact records its own creation as `field_name="status"` carrying
 * `"created"`. Wording by field name alone would relabel another domain's rows
 * — the contact one silently, because `status` is a name a task uses too.
 *
 * **The same row reads differently depending on which feed it is in.** A task's
 * contact membership is projected once, onto the task
 * (`entity_type='task'`, `field_name='contact:{id}'`), and it is read from both
 * ends: on the task's own history the interesting party is the person, and on
 * the person's history it is the task. Neither wording names the other by id,
 * because the only id on the row is the *contact's* — meaningless on their own
 * page, and no use on the task's.
 */

import { TaskStatus } from '@/types/tasks';
import { statusWording } from '@/lib/task-display';

/** The entity whose history is being displayed. */
export type HistoryEntity = 'contact' | 'journal' | 'task';

/** The parts of a history row the wording depends on. */
export interface HistoryRowSubject {
  readonly entity_type: string;
  readonly field_name: string;
  readonly old_value: string | null;
  readonly new_value: string | null;
  /** The task's name, supplied by the read when the row cannot carry it. */
  readonly entity_label?: string | null;
}

const TASK_ENTITY_TYPE = 'task';
const CREATED_MARKER = '__created__';
const DELETED_MARKER = '__deleted__';
const CONTACT_FIELD_PREFIX = 'contact:';
const JOURNAL_FIELD_PREFIX = 'journal:';

/** Word a task status value the way every other task surface words it. */
function status(value: string | null): string {
  return value ? statusWording(value as TaskStatus) : 'unknown';
}

/**
 * Describe a task history row, or `null` to leave it to the generic wording.
 *
 * `null` is returned for every row this function has nothing better to say
 * about — another domain's row, and a task's own `text` change, which
 * `formatActivityDescription` already renders as
 * *Changed Text from "…" to "…"*.
 */
export function taskEntryDescription(
  row: HistoryRowSubject,
  surface: HistoryEntity
): string | null {
  if (row.entity_type !== TASK_ENTITY_TYPE) return null;

  const { field_name, old_value, new_value } = row;

  /**
   * Append the task's name when the read supplied one.
   *
   * A task has no route, so this is the only thing that turns "Linked to a
   * task" into a record of something. The label is absent while projection
   * catches up, and the unnamed wording is the honest answer then — a
   * placeholder would claim the task has no name rather than that we do not
   * know it yet.
   */
  function named(description: string): string {
    return row.entity_label
      ? `${description}: “${row.entity_label}”`
      : description;
  }

  if (field_name === CREATED_MARKER) {
    return new_value ? `Task created: “${new_value}”` : 'Task created';
  }

  if (field_name === DELETED_MARKER) return named('Task deleted');

  if (field_name === 'status') {
    return `Status changed from ${status(old_value)} to ${status(new_value)}`;
  }

  // The values are journal ids, which name nothing a reader can use: the
  // journal the task moved to is on the row itself, not in its history.
  if (field_name === 'due_journal_id') return 'Due journal changed';

  if (field_name.startsWith(JOURNAL_FIELD_PREFIX)) {
    return new_value ? 'Linked to a journal' : 'Unlinked from a journal';
  }

  if (field_name.startsWith(CONTACT_FIELD_PREFIX)) {
    if (surface === 'contact') {
      return named(new_value ? 'Linked to a task' : 'Unlinked from a task');
    }
    // Not named on the task's own feed: the reader is looking at the task.
    return new_value ? 'Linked a contact' : 'Unlinked a contact';
  }

  return null;
}
