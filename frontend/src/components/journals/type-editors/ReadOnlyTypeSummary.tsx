import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export interface ReadOnlyTypeSummaryItem {
  readonly label: string;
  readonly value: ReactNode;
  readonly fullWidth?: boolean;
}

interface ReadOnlyTypeSummaryProps {
  readonly items: readonly ReadOnlyTypeSummaryItem[];
  readonly testId: string;
  readonly className?: string;
}

export function ReadOnlyTypeSummary({
  items,
  testId,
  className,
}: ReadOnlyTypeSummaryProps) {
  return (
    <div
      className={cn('bg-muted/20 rounded-md border p-4', className)}
      data-testid={testId}
    >
      <div className='grid grid-cols-1 gap-3 md:grid-cols-2'>
        {items.map(item => (
          <div
            key={item.label}
            className={cn(
              'bg-background space-y-1 rounded-sm px-3 py-2 shadow-sm',
              item.fullWidth && 'md:col-span-2'
            )}
          >
            <p className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>
              {item.label}
            </p>
            <div className='text-sm font-semibold break-words'>
              {item.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SummaryBadgeList({
  values,
}: {
  readonly values: readonly string[];
}) {
  return (
    <div className='flex flex-wrap gap-2'>
      {values.map(value => (
        <Badge key={value} variant='secondary'>
          {value}
        </Badge>
      ))}
    </div>
  );
}
