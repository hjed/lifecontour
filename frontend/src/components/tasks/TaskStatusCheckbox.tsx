'use client';

import { Checkbox } from '@/components/ui/checkbox';
import { useTaskWriteInFlight, useUpdateTask } from '@/lib/api/tasks';
import { statusActions } from '@/lib/task-display';
import { TaskStatus, type ListTaskReadResource } from '@/types/tasks';

interface TaskStatusCheckboxProps {
  readonly task: ListTaskReadResource;
  readonly describedById?: string;
}

function moveTo(task: ListTaskReadResource, done: boolean) {
  const target = done ? TaskStatus.DONE : TaskStatus.NOT_DONE;
  return statusActions(task.attributes.status, { onList: true }).find(
    action => action.target === target
  );
}

export function TaskStatusCheckbox({
  task,
  describedById,
}: TaskStatusCheckboxProps) {
  const update = useUpdateTask();
  const writing = useTaskWriteInFlight(task.id);
  const { status, text } = task.attributes;

  const toggle = (checked: boolean) => {
    if (writing) return;
    const action = moveTo(task, checked);
    if (action) update.mutate({ taskId: task.id, status: action.target });
  };

  return (
    <Checkbox
      checked={status !== TaskStatus.NOT_DONE}
      onCheckedChange={checked => toggle(checked === true)}
      aria-label={`Done: ${text}`}
      aria-describedby={describedById}
      aria-busy={writing}
      aria-disabled={writing || undefined}
      className='after:-inset-[15px]'
    />
  );
}
