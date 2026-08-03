import { useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { AlertCircle, GitMerge, Loader2, Zap } from 'lucide-react';
import {
  useReviewItems,
  useDismissReviewItem,
  useAutoMergeReviewItems,
} from '@/lib/api/journals';
import { MergeJournalDialog } from './MergeJournalDialog';
import { Badge } from '@/components/ui/badge';
import { format } from 'date-fns';

interface ReviewQueueSidebarProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

function EmptyQueueState() {
  return (
    <div className='text-muted-foreground p-8 text-center'>
      <AlertCircle className='mx-auto mb-3 h-8 w-8 opacity-50' />
      <p>Your review queue is empty.</p>
      <p className='mt-1 text-sm'>No pending AI suggestions.</p>
    </div>
  );
}

export function ReviewQueueSidebar({
  open,
  onOpenChange,
}: ReviewQueueSidebarProps) {
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null
  );

  const { data, isLoading } = useReviewItems('pending', 1, 50);
  const totalCount = (data?.meta?.total_count as number) || 0;
  const items = data?.data || [];

  const dismissMutation = useDismissReviewItem();
  const autoMergeMutation = useAutoMergeReviewItems();

  const handleReviewClick = (sourceId: number, candidateId: number) => {
    setSelectedSourceId(sourceId.toString());
    setSelectedCandidateId(candidateId.toString());
    setMergeDialogOpen(true);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className='w-full overflow-y-auto sm:max-w-md'>
        <SheetHeader className='mb-6'>
          <SheetTitle className='flex items-center gap-2'>
            Review Queue
            {totalCount > 0 && (
              <Badge variant='destructive' className='ml-2 font-mono'>
                {totalCount}
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription>
            AI-generated suggestions for journals that may be duplicates or
            related.
          </SheetDescription>
        </SheetHeader>

        {isLoading ? (
          <div className='text-muted-foreground flex items-center justify-center p-8'>
            <Loader2 className='mr-2 h-4 w-4 animate-spin' />
            Loading queue...
          </div>
        ) : items.length === 0 ? (
          <EmptyQueueState />
        ) : (
          <div className='space-y-4'>
            <Button
              variant='outline'
              size='sm'
              className='w-full'
              onClick={() => autoMergeMutation.mutate()}
              disabled={autoMergeMutation.isPending}
              data-testid='auto-merge-all-btn'
            >
              {autoMergeMutation.isPending ? (
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
              ) : (
                <Zap className='mr-2 h-4 w-4' />
              )}
              Merge All Identical
            </Button>
            {items.map(item => {
              const { attributes, id } = item;
              const {
                source_journal,
                candidate_journal,
                reason,
                confidence_score,
              } = attributes;

              return (
                <div
                  key={id}
                  className='border-destructive/20 bg-destructive/5 space-y-3 rounded-lg border p-4'
                >
                  <div className='flex items-start justify-between gap-2'>
                    <div className='text-destructive flex items-center gap-1.5 text-sm font-medium'>
                      <AlertCircle className='h-3.5 w-3.5' />
                      {reason.replace('_', ' ')}
                    </div>
                    <div className='text-muted-foreground bg-background rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase'>
                      {Math.round(confidence_score * 100)}% Match
                    </div>
                  </div>

                  <div className='space-y-2 text-sm'>
                    <div className='flex items-center justify-between'>
                      <Link
                        href={`/journals/${source_journal.id}` as Route}
                        className='font-medium hover:underline focus:outline-none'
                        onClick={() => onOpenChange(false)}
                      >
                        {source_journal.title}
                      </Link>
                      <span className='text-muted-foreground text-xs'>
                        {format(
                          new Date(source_journal.event_date_range.start),
                          'MMM d, yyyy'
                        )}
                      </span>
                    </div>
                    <div className='text-muted-foreground text-xs font-medium'>
                      may be a duplicate of
                    </div>
                    <div className='flex items-center justify-between'>
                      <Link
                        href={`/journals/${candidate_journal.id}` as Route}
                        className='font-medium hover:underline focus:outline-none'
                        onClick={() => onOpenChange(false)}
                      >
                        {candidate_journal.title}
                      </Link>
                      <span className='text-muted-foreground text-xs'>
                        {format(
                          new Date(candidate_journal.event_date_range.start),
                          'MMM d, yyyy'
                        )}
                      </span>
                    </div>
                  </div>

                  <div className='flex justify-end gap-2 pt-2'>
                    <Button
                      variant='outline'
                      size='sm'
                      className='border-destructive text-destructive hover:bg-destructive w-full text-xs hover:text-white'
                      onClick={() => dismissMutation.mutate(id.toString())}
                      disabled={dismissMutation.isPending}
                      data-testid={`queue-dismiss-btn-${id}`}
                    >
                      Dismiss
                    </Button>
                    <Button
                      variant='destructive'
                      size='sm'
                      className='w-full text-xs'
                      onClick={() =>
                        handleReviewClick(
                          source_journal.id,
                          candidate_journal.id
                        )
                      }
                      data-testid={`queue-confirm-match-btn-${id}`}
                    >
                      <GitMerge className='mr-1.5 h-3.5 w-3.5' />
                      Confirm Match
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {selectedSourceId && selectedCandidateId && (
          <MergeJournalDialog
            sourceJournalId={selectedSourceId}
            targetJournalId={selectedCandidateId}
            // The queue only ever flags journals as being the *same* thing
            // (external_link_match, duplicate_journal, needs_review), so
            // confirming a match must not add the two activities together.
            defaultFitnessMergeMode='replace'
            open={mergeDialogOpen}
            onOpenChange={open => {
              setMergeDialogOpen(open);
              if (!open) {
                setTimeout(() => {
                  setSelectedSourceId(null);
                  setSelectedCandidateId(null);
                }, 300);
              }
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}
