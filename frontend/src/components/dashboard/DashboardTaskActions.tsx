/**
 * The inline done action on a dashboard task row (**W24**).
 *
 * An `outline` `size="sm"` **Done** button with a check icon, top-right of the
 * text row, wrapping under the text when the column is narrow, and never
 * navigating away.
 *
 * **One button, and that is the whole offer.** Everything on the dashboard is
 * not-done and future-dated, so completion is the only status move a row here
 * can make. The journal surface carries the way back and the ordinary cancel
 * beside it, and delete and retarget are journal-only (wireframe gaps 8 and
 * 10): the dashboard is where a commitment is *reminded of*, not where it is
 * worked with. The wording comes from `MARK_DONE` in `lib/task-display` rather
 * than being written again here, so the two surfaces cannot name the same
 * button two ways.
 *
 * **The optimistic update and its rollback belong to `useUpdateTask`, not
 * here** — the criterion pairs the optimism with `invalidateAfterMutation`,
 * which is the hook's responsibility, and the journal row presses the same
 * hook. What the hook does for *this* surface is take the row out of the
 * cached dashboard section, because a task that is no longer not-done is no
 * longer in it.
 *
 * The group carries `aria-busy`, not the button that was pressed: the
 * optimistic removal rewrites the section before the request settles, so on a
 * real card the pressed control is gone by the time it does — the correction
 * ITER18-001 Phase 17 recorded as its decision 8b.
 */

'use client';

import { Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTaskWriteInFlight, useUpdateTask } from '@/lib/api/tasks';
import { MARK_DONE } from '@/lib/task-display';

interface DashboardTaskActionsProps {
  /**
   * The task this acts on, as the dashboard numbers it.
   *
   * The one place the payload's `task_id` meets the task API, which keys
   * everything by string. Converted here and used for both the write and the
   * in-flight lock, so the two cannot disagree about which task is busy.
   */
  readonly taskId: number;
  /**
   * The id of the element carrying the task's text.
   *
   * Every row's button is named the same thing, so the group is *described by*
   * the commitment it belongs to rather than each button being given a label
   * long enough to identify it — the arrangement `JournalTaskActions`
   * established.
   */
  readonly describedById: string;
}

export function DashboardTaskActions({
  taskId,
  describedById,
}: DashboardTaskActionsProps) {
  const update = useUpdateTask();
  const id = String(taskId);

  // One write at a time per *task*, read from the mutation cache rather than
  // from this hook instance: a journal open in another tab of the app, or a
  // retarget dialog, is a write against the same task and should lock this
  // button too.
  const writing = useTaskWriteInFlight(id);

  return (
    <div
      role='group'
      aria-label='Task actions'
      aria-describedby={describedById}
      aria-busy={writing}
      className='flex flex-wrap items-center gap-1.5'
    >
      <Button
        type='button'
        variant='outline'
        size='sm'
        aria-label={MARK_DONE.accessibleName}
        disabled={writing}
        data-testid='dashboard-task-action-done'
        onClick={() => {
          update.mutate({ taskId: id, status: MARK_DONE.target });
        }}
      >
        <Check aria-hidden='true' />
        {MARK_DONE.label}
      </Button>
    </div>
  );
}
