/**
 * JournalParentSelector component for setting/changing/removing the parent journal.
 *
 * Displays the current parent journal (if any) with a link and remove button.
 * Provides a popover with JournalSearchCombobox for setting or changing the parent.
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { BookOpen, X, ArrowUpRight, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import type { ParentJournalSummary, JournalResource } from '@/types/journals';
import { JournalSearchCombobox } from './JournalSearchCombobox';

interface JournalParentSelectorProps {
  /** ID of the current journal (excluded from search results to prevent cycles) */
  readonly currentJournalId: string;
  /** The current parent journal, if any */
  readonly parent?: ParentJournalSummary | null;
  /** Callback when a new parent journal is selected */
  readonly onParentChange: (parentId: string) => Promise<void>;
  /** Callback when the parent is removed */
  readonly onParentRemove: () => Promise<void>;
  readonly disabled?: boolean;
  readonly className?: string;
}

/**
 * Parent journal selector with inline display, search, and remove.
 */
export function JournalParentSelector({
  currentJournalId,
  parent,
  onParentChange,
  onParentRemove,
  disabled = false,
  className,
}: JournalParentSelectorProps) {
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSelect = async (journal: JournalResource) => {
    setIsLoading(true);
    try {
      await onParentChange(journal.id);
      setIsPopoverOpen(false);
    } catch (error) {
      console.error('Failed to set parent:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemove = async () => {
    setIsLoading(true);
    try {
      await onParentRemove();
    } catch (error) {
      console.error('Failed to remove parent:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className={cn('flex items-center gap-2', className)}
      data-testid='parent-selector'
    >
      {parent ? (
        <>
          {/* Current parent display */}
          <div className='flex items-center gap-2'>
            <BookOpen className='text-muted-foreground h-4 w-4 flex-shrink-0' />
            <Link
              href={`/journals/${parent.id}` as Route}
              className='hover:text-primary text-sm font-medium transition-colors'
            >
              {parent.title}
              <ArrowUpRight className='ml-1 inline h-3 w-3' />
            </Link>
          </div>

          {/* Change parent button */}
          <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
            <PopoverTrigger asChild>
              <Button
                variant='outline'
                size='sm'
                className='h-6 gap-1 text-xs'
                disabled={disabled || isLoading}
                aria-label='Change parent journal'
              >
                Change Parent
              </Button>
            </PopoverTrigger>
            <PopoverContent className='w-80 p-3' align='start'>
              <div className='space-y-2'>
                <Label htmlFor='parent-journal-search'>
                  Select Parent Journal
                </Label>
                <JournalSearchCombobox
                  onSelect={handleSelect}
                  placeholder='Search for a parent journal...'
                  inputId='parent-journal-search'
                  excludeJournalId={currentJournalId}
                  disabled={isLoading}
                />
              </div>
            </PopoverContent>
          </Popover>

          {/* Remove parent button */}
          <Button
            title='Removing a parent is temporarily disabled until backend explicitly supports null updates'
            variant='ghost'
            size='sm'
            onClick={handleRemove}
            disabled={true}
            className='h-6 w-6 p-0'
            aria-label='Remove parent journal'
          >
            <X className='h-3 w-3' />
          </Button>
        </>
      ) : (
        /* No parent — show "Set Parent" button with popover */
        <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
          <PopoverTrigger asChild>
            <Button
              variant='outline'
              size='sm'
              className='h-6 gap-1 text-xs'
              disabled={disabled || isLoading}
              aria-label='Set parent journal'
            >
              <Plus className='h-3 w-3' />
              Set Parent
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-80 p-3' align='start'>
            <div className='space-y-2'>
              <Label htmlFor='parent-journal-search'>
                Select Parent Journal
              </Label>
              <JournalSearchCombobox
                onSelect={handleSelect}
                placeholder='Search for a parent journal...'
                inputId='parent-journal-search'
                excludeJournalId={currentJournalId}
                disabled={isLoading}
              />
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
