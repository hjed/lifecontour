import { Flag } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TaskFlagMarkerProps {
  readonly className?: string;
}

export function TaskFlagMarker({ className }: TaskFlagMarkerProps) {
  return (
    <Flag
      role='img'
      aria-label='Flagged'
      data-testid='task-flag'
      className={cn('text-warning size-4 shrink-0 fill-current', className)}
    />
  );
}
