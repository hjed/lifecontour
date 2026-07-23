/**
 * WidgetEmptyState — the shared "nothing here" panel for logbook widgets.
 *
 * A centred muted icon above a short message. The dashboard widgets sit
 * side-by-side in the bento grid, so a centred block reads as a deliberate
 * state rather than a stray line of text at the top of an otherwise blank card.
 */

import { cn } from '@/lib/utils';

interface WidgetEmptyStateProps {
  /** Lucide icon component, rendered muted and decorative. */
  readonly icon: React.ComponentType<{
    className?: string;
    'aria-hidden'?: boolean | 'true' | 'false';
  }>;
  readonly message: string;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

export function WidgetEmptyState({
  icon: Icon,
  message,
  className,
  'data-testid': testId,
}: WidgetEmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-1 flex-col items-center justify-center gap-2.5 py-6 text-center',
        className
      )}
      data-testid={testId}
    >
      <Icon className='text-muted-foreground h-6 w-6' aria-hidden='true' />
      <p className='text-muted-foreground text-sm'>{message}</p>
    </div>
  );
}
