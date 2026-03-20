'use client';

import { useState } from 'react';
import { GitMerge } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { JournalSearchCombobox } from './JournalSearchCombobox';
import { useMergeJournal } from '@/lib/api/journals';
import { JournalResource } from '@/types/journals';

interface MergeJournalDialogProps {
  readonly targetJournalId: string;
}

export function MergeJournalDialog({
  targetJournalId,
}: MergeJournalDialogProps) {
  const [open, setOpen] = useState(false);
  const [selectedJournal, setSelectedJournal] =
    useState<JournalResource | null>(null);
  const mergeJournalData = useMergeJournal();

  const handleMerge = async () => {
    if (!selectedJournal) return;

    try {
      await mergeJournalData.mutateAsync({
        targetId: targetJournalId,
        sourceId: selectedJournal.id,
      });
      setOpen(false);
      setSelectedJournal(null);
    } catch {
      // Error is handled by the mutation's onError (toast)
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      // Reset state when closing
      setSelectedJournal(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          variant='outline'
          size='sm'
          className='gap-2'
          aria-label='Merge journal'
        >
          <GitMerge className='h-4 w-4' />
        </Button>
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Merge Another Journal</DialogTitle>
          <DialogDescription>
            Select a source journal to merge INTO this journal. The selected
            journal will be deleted and its data (tags, relationships, types)
            will be merged here. Non-conflicting content will be appended.
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-4 py-4'>
          <div className='flex flex-col gap-2'>
            <span className='text-sm font-medium'>Find Source Journal</span>
            <JournalSearchCombobox
              onSelect={setSelectedJournal}
              excludeJournalId={targetJournalId}
              placeholder='Search by title...'
            />
          </div>

          {selectedJournal && (
            <div className='bg-muted rounded-md p-3 text-sm'>
              <strong>Selected to merge:</strong>{' '}
              {selectedJournal.attributes.title || 'Untitled Journal'}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant='outline' onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleMerge}
            disabled={!selectedJournal || mergeJournalData.isPending}
            className='bg-destructive hover:bg-destructive/90 text-destructive-foreground'
          >
            {mergeJournalData.isPending
              ? 'Merging...'
              : 'Merge and Delete Source'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
