import { openTasksSummary } from '@/lib/task-display';
import type { TaskListAttributes } from '@/types/task-lists';
import type { ListTaskReadResource } from '@/types/tasks';
import { TaskIconGlyph } from './TaskIconGlyph';

interface TaskListHeaderProps extends Pick<
  TaskListAttributes,
  'name' | 'icon'
> {
  readonly tasks: readonly ListTaskReadResource[];
}

export function TaskListHeader({ name, icon, tasks }: TaskListHeaderProps) {
  return (
    <div className='flex items-center gap-4'>
      {icon && (
        <span
          data-testid='task-list-icon'
          className='bg-muted text-foreground flex size-11 shrink-0 items-center justify-center rounded-lg'
        >
          <TaskIconGlyph icon={icon} className='size-5' />
        </span>
      )}
      <div className='min-w-0 flex-1'>
        <h1 className='text-2xl font-semibold wrap-anywhere'>{name}</h1>
        <p
          data-testid='task-list-summary'
          className='text-muted-foreground text-sm'
        >
          {openTasksSummary(tasks)}
        </p>
      </div>
    </div>
  );
}
