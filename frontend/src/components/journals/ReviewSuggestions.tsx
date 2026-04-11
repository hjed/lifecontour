import React, { useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { AlertCircle, GitMerge } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { MergeJournalDialog } from './MergeJournalDialog';
import { ReviewSuggestion } from '@/types/journals';

interface ReviewSuggestionsProps {
  readonly journalId: string;
  readonly suggestions: ReviewSuggestion[];
}

export function ReviewSuggestions({
  journalId,
  suggestions,
}: ReviewSuggestionsProps) {
  const [mergeDialogOpen, setMergeDialogOpen] = useState<boolean>(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null
  );

  if (!suggestions || suggestions.length === 0) {
    return null;
  }

  const handleReviewClick = (candidateId: number) => {
    setSelectedCandidateId(candidateId.toString());
    setMergeDialogOpen(true);
  };

  return (
    <div className='mb-6 space-y-4' data-testid='review-suggestions-container'>
      {suggestions.map(suggestion => (
        <Alert
          key={suggestion.id}
          variant='destructive'
          className='bg-destructive/10 text-destructive border-destructive/20 relative'
        >
          <AlertCircle className='h-4 w-4' />
          <AlertTitle className='font-semibold'>Review Required</AlertTitle>
          <AlertDescription className='mt-2 flex flex-col justify-between gap-4 sm:flex-row sm:items-center'>
            <div>
              <p>
                Potential {suggestion.reason.replace('_', ' ')} detected with{' '}
                <Link
                  href={`/journals/${suggestion.candidate_journal_id}` as Route}
                  className='hover:text-destructive/80 font-medium underline underline-offset-2'
                >
                  {suggestion.candidate_journal_title}
                </Link>
                .
              </p>
              <p className='mt-1 text-xs opacity-80'>
                Confidence: {Math.round(suggestion.confidence_score * 100)}%
              </p>
            </div>
            <div className='flex shrink-0 gap-2'>
              <Button
                variant='destructive'
                size='sm'
                className='whitespace-nowrap'
                onClick={() =>
                  handleReviewClick(suggestion.candidate_journal_id)
                }
                data-testid={`review-btn-${suggestion.id}`}
              >
                <GitMerge className='mr-2 h-4 w-4' />
                Resolve Merge
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      ))}

      {/* Merge Dialog Integration - uses the target journal as the 'source' the user is looking at and candidate as the merge target */}
      {selectedCandidateId && (
        <MergeJournalDialog
          sourceJournalId={journalId}
          targetJournalId={selectedCandidateId}
          open={mergeDialogOpen}
          onOpenChange={open => {
            setMergeDialogOpen(open);
            if (!open) {
              // Note: We don't clear the selected ID immediately to prevent the modal from flashing empty while closing
              setTimeout(() => setSelectedCandidateId(null), 300);
            }
          }}
        />
      )}
    </div>
  );
}
