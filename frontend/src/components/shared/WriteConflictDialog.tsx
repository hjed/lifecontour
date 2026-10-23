'use client';

/**
 * Asks the user how to settle a write the server refused because the record
 * changed since they loaded it (a `412`; see `lib/write-conflicts.ts`).
 *
 * The record's version covers all of it, so the wording names the record and
 * what changed in it — which may be a different part from the one the user
 * edited — rather than implying the same field was changed twice. By the time
 * this shows, the page already displays the other version; "Use theirs" just
 * closes the dialog and "Keep mine" sends the user's change again on top,
 * staying open with the reason if that fails.
 */

import { useEffect, useState } from 'react';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/AuthProvider';
import {
  dismissWriteConflict,
  resetWriteConflicts,
  useWriteConflicts,
  type WriteConflict,
} from '@/lib/write-conflicts';

function changedSummary({ kind, changed }: WriteConflict): string {
  return changed.length > 0
    ? `Changed: ${changed.join(', ')}.`
    : `Another part of this ${kind} changed.`;
}

export function WriteConflictDialog() {
  const [conflict] = useWriteConflicts();
  const { isAuthenticated } = useAuth().state;

  // The store outlives the session; a conflict from before it ended must not
  // offer to replay a write once signed out.
  useEffect(() => {
    if (!isAuthenticated) resetWriteConflicts();
  }, [isAuthenticated]);

  if (!conflict || !isAuthenticated) return null;

  // Keyed so a new conflict starts without the previous one's retry state.
  return <ConflictPrompt key={conflict.id} conflict={conflict} />;
}

function ConflictPrompt({ conflict }: { conflict: WriteConflict }) {
  return conflict.refreshed ? (
    <ChoosePrompt conflict={conflict} />
  ) : (
    <RetryReadPrompt conflict={conflict} />
  );
}

/** The record changed, but the latest version could not be loaded. */
function RetryReadPrompt({ conflict }: { conflict: WriteConflict }) {
  const [isLoading, setIsLoading] = useState(false);

  const tryAgain = async () => {
    setIsLoading(true);
    await conflict.retryRefresh();
    setIsLoading(false);
  };

  return (
    <AlertDialog
      open
      onOpenChange={open => {
        if (!open) dismissWriteConflict(conflict.id);
      }}
    >
      <AlertDialogContent data-testid='write-conflict-dialog'>
        <AlertDialogHeader>
          <AlertDialogTitle>Your change wasn’t saved</AlertDialogTitle>
          <AlertDialogDescription>
            This {conflict.kind} was changed on another tab or device, and the
            latest version couldn’t be loaded.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {conflict.attempted && (
          <p className='text-sm' data-testid='write-conflict-attempted'>
            Your change: {conflict.attempted}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isLoading}>Close</AlertDialogCancel>
          <Button type='button' onClick={tryAgain} disabled={isLoading}>
            Try again
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** The latest version is showing: keep it, or re-apply the change on top. */
function ChoosePrompt({ conflict }: { conflict: WriteConflict }) {
  const [isSaving, setIsSaving] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const keepMine = async () => {
    setIsSaving(true);
    setRetryError(null);
    try {
      await conflict.reapply();
    } catch (error) {
      // The conflict stays open with the change, so the user can try again.
      setRetryError(error instanceof Error ? error.message : String(error));
      setIsSaving(false);
    }
  };

  return (
    <AlertDialog
      open
      onOpenChange={open => {
        // Not while Keep mine is saving: dismissing would drop the conflict,
        // and with it the error and retry should the re-applied write fail.
        if (!open && !isSaving) dismissWriteConflict(conflict.id);
      }}
    >
      <AlertDialogContent data-testid='write-conflict-dialog'>
        <AlertDialogHeader>
          <AlertDialogTitle>Your change wasn’t saved</AlertDialogTitle>
          <AlertDialogDescription>
            This {conflict.kind} was changed on another tab or device after you
            opened it. It now shows the latest version.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className='space-y-2 text-sm'>
          <p data-testid='write-conflict-changed'>{changedSummary(conflict)}</p>
          {conflict.attempted && (
            <p data-testid='write-conflict-attempted'>
              Your change: {conflict.attempted}
            </p>
          )}
          {retryError && (
            <p role='alert' className='text-destructive'>
              Your change still wasn’t saved: {retryError}
            </p>
          )}
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={isSaving}>Use theirs</AlertDialogCancel>
          {/* A plain button, not AlertDialogAction: the dialog must stay open
              until the re-applied write has landed. */}
          <Button type='button' onClick={keepMine} disabled={isSaving}>
            Keep mine
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
