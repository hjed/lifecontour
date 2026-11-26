import {
  TaskStatus,
  type ListTaskReadAttributes,
  type ListTaskReadResource,
  type TaskReadAttributes,
  type TaskReadResource,
} from '@/types/tasks';
import type { TaskListRef } from '@/types/task-lists';

type ResourceOverrides<A> = Partial<A> & { id?: string };

/**
 * A task as a read surface returns it: not done, on no list, in no journal,
 * with no contacts. Each test states only the attributes it is about.
 */
export function createMockTaskRead(
  partial?: ResourceOverrides<TaskReadAttributes>
): TaskReadResource {
  const { id = '1', ...attributes } = partial ?? {};

  return {
    type: 'tasks',
    id,
    attributes: {
      text: 'Print the permit',
      status: TaskStatus.NOT_DONE,
      creating_journal_id: null,
      due_journal_id: null,
      intermediate_journal_ids: [],
      task_list_id: null,
      due_date: null,
      flagged: false,
      icon: null,
      creating_journal: null,
      due_journal: null,
      intermediate_journals: [],
      task_list: null,
      contacts: [],
      lapsed: false,
      lapse_reason: null,
      overdue: false,
      ...attributes,
    },
  };
}

export const PACKING_LIST = {
  id: 7,
  name: 'Packing',
  icon: null,
  archived: false,
} as const satisfies TaskListRef;

/** An undated open task on list 7, "Packing", in no journal. */
export function createMockListTaskRead(
  partial?: ResourceOverrides<ListTaskReadAttributes>
): ListTaskReadResource {
  const task_list = partial?.task_list ?? PACKING_LIST;
  const task_list_id = partial?.task_list_id ?? task_list.id;
  const { id, attributes } = createMockTaskRead(partial);

  return {
    type: 'tasks',
    id,
    attributes: { ...attributes, task_list, task_list_id },
  };
}
