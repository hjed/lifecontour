/**
 * JournalChildrenList component for displaying child journals.
 *
 * Shows a list of child journals with links to navigate to them.
 * Displays title, date, and type information.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import { ChevronRight, Calendar, FileText } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { JournalType, type ChildJournalSummary } from '@/types/journals';

interface JournalChildrenListProps {
  readonly children: ChildJournalSummary[];
  readonly className?: string;
}

/**
 * List component for displaying child journals.
 * Shows child journals with navigation links.
 */
export function JournalChildrenList({
  children,
  className,
}: JournalChildrenListProps) {
  if (children.length === 0) {
    return null;
  }

  return (
    <Card className={className} data-testid='children-list'>
      <CardHeader>
        <CardTitle className='text-lg'>Child Journals</CardTitle>
      </CardHeader>
      <CardContent>
        <div className='space-y-2'>
          {children.map(child => (
            <ChildJournalItem key={child.id} child={child} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

interface ChildJournalItemProps {
  readonly child: ChildJournalSummary;
}

function ChildJournalItem({ child }: ChildJournalItemProps) {
  return (
    <Link
      href={`/journals/${child.id}` as Route}
      className={cn(
        'flex items-center justify-between gap-3 rounded-lg border p-3',
        'hover:bg-muted/50 transition-colors',
        'group'
      )}
      data-testid={`child-item-${child.id}`}
    >
      <div className='flex min-w-0 flex-1 items-center gap-3'>
        {/* Icon based on type */}
        <div className='text-muted-foreground flex-shrink-0'>
          {child.types.includes(JournalType.EVENT) ? (
            <Calendar className='h-4 w-4' />
          ) : (
            <FileText className='h-4 w-4' />
          )}
        </div>

        {/* Title and Date */}
        <div className='min-w-0 flex-1'>
          <div className='group-hover:text-primary truncate font-medium transition-colors'>
            {child.title}
          </div>
          {child.date && (
            <div className='text-muted-foreground text-xs'>
              {new Date(child.date).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
              })}
            </div>
          )}
        </div>

        {/* Type Badges */}
        <div className='flex flex-shrink-0 gap-1'>
          {child.types.map((type: string) => (
            <Badge
              key={type}
              variant='secondary'
              className='h-5 px-1.5 text-[10px]'
            >
              {type}
            </Badge>
          ))}
        </div>
      </div>

      {/* Navigation Arrow */}
      <ChevronRight className='text-muted-foreground group-hover:text-primary h-4 w-4 flex-shrink-0 transition-colors' />
    </Link>
  );
}
