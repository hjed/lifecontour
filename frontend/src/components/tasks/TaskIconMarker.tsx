import { TASK_ICON_DISPLAY } from '@/lib/task-icon-display';
import type { TaskIcon } from '@/types/task-icons';
import { TaskIconGlyph } from './TaskIconGlyph';

interface TaskIconMarkerProps {
  readonly icon: TaskIcon;
  readonly testId: string;
}

/**
 * A task's icon as a row shows it: the glyph, with its name as visually
 * hidden text, because the icon a user picked says something the task's text
 * does not.
 */
export function TaskIconMarker({ icon, testId }: TaskIconMarkerProps) {
  return (
    <span data-testid={testId} className='flex shrink-0'>
      <TaskIconGlyph icon={icon} className='size-4' />
      <span className='sr-only'>{TASK_ICON_DISPLAY[icon].label} icon</span>
    </span>
  );
}
