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
import { Label } from '@/components/ui/label';
import { JournalSearchCombobox } from './JournalSearchCombobox';
import { useMergeJournal, useJournal } from '@/lib/api/journals';
import { JournalResource, MergeOverrides } from '@/types/journals';
import { MergeResolutionDialog } from './MergeResolutionDialog';

interface MergeJournalDialogProps {
  readonly targetJournalId: string;
}

export function MergeJournalDialog({
  targetJournalId,
}: MergeJournalDialogProps) {
  const [open, setOpen] = useState(false);
  const [resolutionOpen, setResolutionOpen] = useState(false);
  const [selectedJournal, setSelectedJournal] =
    useState<JournalResource | null>(null);

  const { data: targetJournalRes } = useJournal(targetJournalId);
  // Only fetch source journal details if one is selected, to compare conflicts
  const { data: sourceJournalRes } = useJournal(selectedJournal?.id || '');

  const mergeJournalData = useMergeJournal();

  const handleNext = () => {
    if (!selectedJournal) return;
    setOpen(false);
    setResolutionOpen(true);
  };

  const handleMerge = async (overrides: MergeOverrides) => {
    if (!selectedJournal) return;

    try {
      await mergeJournalData.mutateAsync({
        targetId: targetJournalId,
        sourceId: selectedJournal.id,
        overrides,
      });
      setResolutionOpen(false);
      setSelectedJournal(null);
    } catch {
      // Error is handled by the mutation's onError (toast)
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      setSelectedJournal(null);
    }
  };

  const handleResolutionOpenChange = (newOpen: boolean) => {
    setResolutionOpen(newOpen);
    if (!newOpen && !mergeJournalData.isPending) {
      // If user cancels resolution, maybe they want to go back to selection?
      // Or just close everything.
      setSelectedJournal(null);
    }
  };

  return (
    <>
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
              Select a source journal to merge INTO this journal. You will be
              able to resolve any data conflicts on the next screen. The
              selected journal will be deleted upon merging.
            </DialogDescription>
          </DialogHeader>

          <div className='space-y-4 py-4'>
            <div className='flex flex-col gap-2'>
              <Label htmlFor='merge-journal-search'>Find Source Journal</Label>
              <JournalSearchCombobox
                inputId='merge-journal-search'
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
            <Button variant='outline' onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleNext}
              disabled={!selectedJournal}
              className='bg-primary text-primary-foreground'
            >
              Next
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {resolutionOpen && (
        <MergeResolutionDialog
          open={resolutionOpen}
          onOpenChange={handleResolutionOpenChange}
          targetJournal={targetJournalRes?.data || null}
          sourceJournal={sourceJournalRes?.data || null}
          isPending={mergeJournalData.isPending}
          onResolve={handleMerge}
        />
      )}
    </>
  );
}
