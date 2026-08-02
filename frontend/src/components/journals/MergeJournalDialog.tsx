'use client';

import { useState, useEffect } from 'react';
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
import {
  FitnessMergeMode,
  JournalResource,
  MergeOverrides,
} from '@/types/journals';
import { MergeResolutionDialog } from './MergeResolutionDialog';

interface MergeJournalDialogProps {
  readonly targetJournalId: string;
  readonly sourceJournalId?: string;
  readonly open?: boolean;
  readonly onOpenChange?: (open: boolean) => void;
}

export function MergeJournalDialog({
  targetJournalId,
  sourceJournalId,
  open: externalOpen,
  onOpenChange: externalOnOpenChange,
}: MergeJournalDialogProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = externalOpen === undefined ? internalOpen : externalOpen;

  const [resolutionOpen, setResolutionOpen] = useState(false);
  const [selectedJournal, setSelectedJournal] =
    useState<JournalResource | null>(null);

  // Auto-select source journal if provided via props
  const { data: initialSourceJournal } = useJournal(
    sourceJournalId && open && !resolutionOpen ? sourceJournalId : ''
  );

  // Use useEffect to apply the source journal when it loads
  useEffect(() => {
    if (
      initialSourceJournal?.data &&
      !selectedJournal &&
      open &&
      !resolutionOpen
    ) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedJournal(initialSourceJournal.data);
      // Auto-open resolution if the UI triggered this from a specific review action
      if (sourceJournalId && externalOpen) {
        setResolutionOpen(true);
      }
    }
  }, [
    initialSourceJournal,
    selectedJournal,
    open,
    resolutionOpen,
    sourceJournalId,
    externalOpen,
  ]);

  const { data: targetJournalRes } = useJournal(targetJournalId);
  // Only fetch source journal details if one is selected, to compare conflicts
  const { data: sourceJournalRes } = useJournal(selectedJournal?.id || '');

  const mergeJournalData = useMergeJournal();

  const handleOpenChange = (newOpen: boolean) => {
    if (externalOnOpenChange) {
      externalOnOpenChange(newOpen);
    } else {
      setInternalOpen(newOpen);
    }
    if (!newOpen) {
      setSelectedJournal(null);
    }
  };

  const handleNext = () => {
    if (!selectedJournal) return;
    if (externalOnOpenChange) {
      externalOnOpenChange(false);
    } else {
      setInternalOpen(false);
    }
    setResolutionOpen(true);
  };

  const handleMerge = async (
    overrides: MergeOverrides,
    fitnessMergeMode: FitnessMergeMode
  ) => {
    if (!selectedJournal) return;

    try {
      await mergeJournalData.mutateAsync({
        targetId: targetJournalId,
        sourceId: selectedJournal.id,
        overrides,
        fitnessMergeMode,
      });
      setResolutionOpen(false);
      setSelectedJournal(null);
      // Notify parent that the dialog should close (e.g., ReviewQueueSidebar)
      if (externalOnOpenChange) {
        externalOnOpenChange(false);
      }
    } catch {
      // Error is handled by the mutation's onError (toast)
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
      <Dialog open={open && !resolutionOpen} onOpenChange={handleOpenChange}>
        {externalOpen === undefined && (
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
        )}
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
          // Keyed on the pair so a different merge starts from the defaults
          // rather than inheriting the previous pair's resolutions. Doing this
          // with an effect instead would fight React Query: a background
          // refetch changes the journal object identity without changing which
          // journals these are, and would reset the user's choices mid-dialog.
          key={`${targetJournalId}:${selectedJournal?.id ?? ''}`}
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
