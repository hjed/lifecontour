import { TASK_ICON_DISPLAY } from '@/lib/task-icon-display';
import type { TaskIcon } from '@/types/task-icons';

interface TaskIconGlyphProps {
  readonly icon: TaskIcon;
  readonly className?: string;
}

/**
 * A task's or a list's icon, drawn as decoration: the text beside it, or the
 * control around it, carries the name.
 */
export function TaskIconGlyph({ icon, className }: TaskIconGlyphProps) {
  const { Icon } = TASK_ICON_DISPLAY[icon];
  return <Icon aria-hidden='true' className={className} />;
}
