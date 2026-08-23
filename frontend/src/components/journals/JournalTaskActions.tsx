/**
 * The inline status actions on a task row (**W24**).
 *
 * The wireframe draws one button — an `outline` `size="sm"` **Done** with a
 * check icon, top-right of the text row, wrapping under the text when the
 * column is narrow, and never navigating away. A journal shows tasks in every
 * status where the dashboard shows only live ones, so the same idiom carries
 * the way back from done and the ordinary cancel beside it.
 *
 * Two rules from the specification are built into what is offered:
 *
 * - **Cancel is the ordinary action and deletion is the exception** — "the UI
 *   should treat cancelling as the normal action and deletion as the
 *   exception". Delete is last, muted, icon-only, and behind a confirmation
 *   that says what cancelling would keep.
 * - **A cancelled task offers no status action.** The service gives cancelled
 *   exactly one exit — retargeting onto a new future journal — and refuses
 *   both status calls out of it, so a button here could only draw a 409. The
 *   offer table in `lib/task-display.ts` is where that rule lives.
 *
 * The optimistic update and its rollback belong to `useUpdateTask`, not here:
 * the criterion pairs them with `invalidateAfterMutation`, which is the hook's
 * responsibility, and the retarget dialog and the dashboard reuse the same
 * hook.
 */

'use client';

import { Ban, Check, RotateCcw, Trash2 } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  useDeleteTask,
  useTaskWriteInFlight,
  useUpdateTask,
} from '@/lib/api/tasks';
import { statusActions, type TaskStatusAction } from '@/lib/task-display';
import type { JournalTaskResource } from '@/types/tasks';

interface JournalTaskActionsProps {
  /** The task these actions act on. */
  readonly task: JournalTaskResource;
  /**
   * The id of the element carrying the task's text.
   *
   * Every row's buttons are named the same thing, so the group is *described*
   * by the commitment it belongs to rather than each button being given a
   * label long enough to identify it.
   */
  readonly describedById: string;
}

/** The glyph each action carries. W24 names the check; the rest follow it. */
const ACTION_ICONS: Record<TaskStatusAction['key'], typeof Check> = {
  done: Check,
  'not-done': RotateCcw,
  cancel: Ban,
};

export function JournalTaskActions({
  task,
  describedById,
}: JournalTaskActionsProps) {
  const update = useUpdateTask();
  const remove = useDeleteTask();

  // One write at a time per *task*, not per component instance. A task holding
  // two roles in this journal is rendered under both headings, so the same
  // commitment has two of these side by side; a guard reading only this
  // instance's `isPending` would leave the twin live, and its second click
  // would race the first write with the server's ordering deciding which move
  // survives. Two overlapping status calls decide against the same stale
  // reading, and the later one wins whatever the first was for.
  const writing = useTaskWriteInFlight(task.id);
  const actions = statusActions(task.attributes.status);

  // The *group* carries the busy state, not the control that was pressed: the
  // optimistic patch flips the row to its new status before the request
  // settles, so the button that was clicked is gone by the time it does.
  return (
    <div
      role='group'
      aria-label='Task actions'
      aria-describedby={describedById}
      aria-busy={writing}
      className='flex flex-wrap items-center gap-1.5'
    >
      {actions.map(action => {
        const Icon = ACTION_ICONS[action.key];

        return (
          <Button
            key={action.key}
            type='button'
            variant='outline'
            size='sm'
            aria-label={action.accessibleName}
            disabled={writing}
            data-testid={`journal-task-action-${action.key}`}
            onClick={() => {
              update.mutate({ taskId: task.id, status: action.target });
            }}
          >
            <Icon aria-hidden='true' />
            {action.label}
          </Button>
        );
      })}

      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            type='button'
            variant='ghost'
            size='sm'
            aria-label='Delete task'
            disabled={writing}
            title='Delete task'
            data-testid='journal-task-action-delete'
            className='text-muted-foreground hover:text-destructive'
          >
            <Trash2 aria-hidden='true' />
          </Button>
        </AlertDialogTrigger>

        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this task?</AlertDialogTitle>
            <AlertDialogDescription>
              Deleting is permanent and removes the task from every journal it
              is linked to. Cancel it instead and it stays part of the record,
              and can be reopened later by giving it a new due journal.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep task</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                remove.mutate(task.id);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
