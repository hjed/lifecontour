/**
 * JournalChildrenList component for displaying child journals.
 *
 * Shows a list of child journals with links to navigate to them.
 * Displays title, date, and type information.
 * Optionally provides an "Add Child Journal" action when parentId is given.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import { ChevronRight, Calendar, FileText, Plus } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { JournalType, type ChildJournalSummary } from '@/types/journals';
import { JournalTypeBadges } from './JournalTypeBadges';

interface JournalChildrenListProps {
  readonly childJournals: ChildJournalSummary[];
  readonly parentId?: string;
  readonly className?: string;
}

/**
 * List component for displaying child journals.
 * Shows child journals with navigation links and an optional add-child action.
 */
export function JournalChildrenList({
  childJournals,
  parentId,
  className,
}: JournalChildrenListProps) {
  if (childJournals.length === 0 && !parentId) {
    return null;
  }

  return (
    <Card className={className} data-testid='children-list'>
      <CardHeader className='flex flex-row items-center justify-between space-y-0'>
        <CardTitle className='text-lg'>Child Journals</CardTitle>
        {parentId && (
          <Button variant='outline' size='sm' asChild>
            <Link
              href={`/journals/new?parentId=${parentId}` as Route}
              aria-label='Add child journal'
            >
              <Plus className='mr-1 h-4 w-4' />
              Add Child
            </Link>
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {childJournals.length > 0 ? (
          <div className='space-y-2'>
            {childJournals.map(child => (
              <ChildJournalItem key={child.id} child={child} />
            ))}
          </div>
        ) : (
          <p className='text-muted-foreground text-sm'>
            No child journals yet. Click &quot;Add Child&quot; to create one.
          </p>
        )}
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
        <JournalTypeBadges
          types={child.types}
          className='flex-shrink-0 gap-1 [&>*]:h-5 [&>*]:px-1.5 [&>*]:text-[10px]'
        />
      </div>

      {/* Navigation Arrow */}
      <ChevronRight className='text-muted-foreground group-hover:text-primary h-4 w-4 flex-shrink-0 transition-colors' />
    </Link>
  );
}
