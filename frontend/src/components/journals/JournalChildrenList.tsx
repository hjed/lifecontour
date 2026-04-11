/**
 * JournalChildrenList component for displaying child journals.
 *
 * Shows a list of child journals with links to navigate to them.
 * Displays title, date, and type information.
 * Optionally provides "Add Child Journal" and "Add Existing" actions.
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { format, parseISO } from 'date-fns';
import { ChevronRight, Calendar, FileText, Plus, Link2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import {
  JournalType,
  type ChildJournalSummary,
  type JournalResource,
} from '@/types/journals';
import { JournalTypeBadges } from './JournalTypeBadges';
import { JournalSearchCombobox } from './JournalSearchCombobox';

interface JournalChildrenListProps {
  readonly childJournals: ChildJournalSummary[];
  readonly parentId?: string;
  /** Callback to add an existing journal as a child. Receives the selected journal's ID. */
  readonly onAddExisting?: (journalId: string) => Promise<void>;
  readonly className?: string;
}

/**
 * List component for displaying child journals.
 * Shows child journals with navigation links and an optional add-child action.
 */
export function JournalChildrenList({
  childJournals,
  parentId,
  onAddExisting,
  className,
}: JournalChildrenListProps) {
  const [isAddExistingOpen, setIsAddExistingOpen] = useState(false);
  const [isAddingExisting, setIsAddingExisting] = useState(false);

  if (childJournals.length === 0 && !parentId) {
    return null;
  }

  const handleAddExisting = async (journal: JournalResource) => {
    if (!onAddExisting) return;
    setIsAddingExisting(true);
    try {
      await onAddExisting(journal.id);
      setIsAddExistingOpen(false);
    } catch (error) {
      console.error('Failed to add existing journal as child:', error);
    } finally {
      setIsAddingExisting(false);
    }
  };

  return (
    <Card className={className} data-testid='children-list'>
      <CardHeader className='flex flex-row items-center justify-between space-y-0'>
        <CardTitle className='text-lg'>Child Journals</CardTitle>
        {parentId && (
          <div className='flex items-center gap-2'>
            {/* Add Existing Button */}
            {onAddExisting && (
              <Popover
                open={isAddExistingOpen}
                onOpenChange={setIsAddExistingOpen}
              >
                <PopoverTrigger asChild>
                  <Button
                    variant='outline'
                    size='sm'
                    disabled={isAddingExisting}
                    aria-label='Add existing journal as child'
                  >
                    <Link2 className='mr-1 h-4 w-4' />
                    Add Existing
                  </Button>
                </PopoverTrigger>
                <PopoverContent className='w-80 p-3' align='end'>
                  <div className='space-y-2'>
                    <Label htmlFor='add-existing-child-search'>
                      Search for a journal to add as child
                    </Label>
                    <JournalSearchCombobox
                      onSelect={handleAddExisting}
                      placeholder='Search journals...'
                      inputId='add-existing-child-search'
                      excludeJournalId={parentId}
                      disabled={isAddingExisting}
                    />
                  </div>
                </PopoverContent>
              </Popover>
            )}

            {/* Create New Child Button */}
            <Button variant='outline' size='sm' asChild>
              <Link
                href={`/journals/new?parentId=${parentId}` as Route}
                aria-label='Add child journal'
              >
                <Plus className='mr-1 h-4 w-4' />
                Add Child
              </Link>
            </Button>
          </div>
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
              {format(parseISO(child.date), 'MMM d, yyyy')}
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
