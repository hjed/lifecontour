/**
 * The task-list and list-task request types refuse the bodies the backend
 * refuses, so an invalid request does not compile.
 *
 * The `@ts-expect-error` lines are the assertions: `pnpm type-check` fails if
 * any of them stops being an error, which is exactly the regression they
 * guard — a widened type that would let a 400 through from typed code.
 */

import { TASK_ICONS, type TaskIcon } from '@/types/task-icons';
import type {
  TaskListCreateInput,
  TaskListUpdateInput,
} from '@/types/task-lists';
import type { ListTaskCreateInput, TaskUpdateInput } from '@/types/tasks';
import { TaskStatus } from '@/types/tasks';

describe('TASK_ICONS', () => {
  it('holds the 40 published keys, each once', () => {
    expect(TASK_ICONS).toHaveLength(40);
    expect(new Set(TASK_ICONS).size).toBe(TASK_ICONS.length);
  });

  it('keeps the published order, which is the order the picker shows', () => {
    expect(TASK_ICONS[0]).toBe('list');
    expect(TASK_ICONS[TASK_ICONS.length - 1]).toBe('camera');
  });

  it('uses kebab-case keys and never offers a flag icon', () => {
    TASK_ICONS.forEach(key => expect(key).toMatch(/^[a-z]+(-[a-z]+)*$/));
    expect(TASK_ICONS).not.toContain('flag');
  });
});

describe('request types', () => {
  it('accepts the legitimate shapes', () => {
    const icon: TaskIcon = 'luggage';
    const inputs: unknown[] = [
      { name: 'Packing' } satisfies TaskListCreateInput,
      { name: 'Packing', icon } satisfies TaskListCreateInput,
      { listId: '1', name: 'Trip' } satisfies TaskListUpdateInput,
      { listId: '1', icon: null } satisfies TaskListUpdateInput,
      { listId: '1', text: 'Tent' } satisfies ListTaskCreateInput,
      {
        listId: '1',
        text: 'Tent',
        due_date: '2026-12-01',
      } satisfies ListTaskCreateInput,
      {
        listId: '1',
        text: 'Tent',
        due_journal_id: 4,
      } satisfies ListTaskCreateInput,
      { taskId: '1', flagged: true } satisfies TaskUpdateInput,
      { taskId: '1', icon: null } satisfies TaskUpdateInput,
      { taskId: '1', due_date: null } satisfies TaskUpdateInput,
      { taskId: '1', due_journal_id: 7 } satisfies TaskUpdateInput,
      {
        taskId: '1',
        status: TaskStatus.NOT_DONE,
        acknowledge_reopen: true,
      } satisfies TaskUpdateInput,
    ];

    expect(inputs).toHaveLength(12);
  });

  it('refuses the shapes the backend refuses', () => {
    const refused: unknown[] = [
      // An icon outside the fixed set.
      // @ts-expect-error -- not a TaskIcon key
      { name: 'Packing', icon: 'flag' } satisfies TaskListCreateInput,
      // A rename naming no change: the backend answers 400.
      // @ts-expect-error -- at least one of name and icon is required
      { listId: '1' } satisfies TaskListUpdateInput,
      // A list must have a name; null is refused.
      // @ts-expect-error -- name cannot be cleared
      { listId: '1', name: null } satisfies TaskListUpdateInput,
      // A due date and a due journal together.
      // The checker reports this one on the closing line, so it carries the directive.
      {
        listId: '1',
        text: 'Tent',
        due_date: '2026-12-01',
        due_journal_id: 4,
        // @ts-expect-error -- due_date and due_journal_id are exclusive
      } satisfies ListTaskCreateInput,
      // A task update naming no change.
      // @ts-expect-error -- at least one change is required
      { taskId: '1' } satisfies TaskUpdateInput,
      // The flag is on or off; null is refused.
      // @ts-expect-error -- flagged is a boolean
      { taskId: '1', flagged: null } satisfies TaskUpdateInput,
      // A due date beside a due journal: the backend refuses the pair.
      {
        taskId: '1',
        due_date: '2026-12-01',
        due_journal_id: 5,
        // @ts-expect-error -- due_date and due_journal_id are exclusive
      } satisfies TaskUpdateInput,
      // The acknowledgement is not a change on its own.
      // @ts-expect-error -- acknowledge_reopen alone changes nothing
      { taskId: '1', acknowledge_reopen: true } satisfies TaskUpdateInput,
    ];

    expect(refused).toHaveLength(8);
  });
});
