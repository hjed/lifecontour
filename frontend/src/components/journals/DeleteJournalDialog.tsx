/**
 * The journal delete confirmation, and the explanation when it is refused.
 *
 * A journal is anchored to by a task in one of two roles — the journal the
 * commitment arose in, and the journal it is due in — and deleting either is
 * refused whatever the task's status, because a done task's link to the
 * journal it was created in is part of the record. The backend answers that
 * refusal as a 409 `JOURNAL_HAS_ANCHORED_TASKS` carrying every blocker as data:
 * the task's text, its status, the roles it blocks in, and the id **and** title
 * of a journal where it can be actioned.
 *
 * Three decisions shape what is below.
 *
 * **The refusal is rendered in place, not toasted.** The specification asks
 * that the failure be explanatory rather than opaque, and what makes it
 * actionable is a set of links to follow. A toast takes those away a few
 * seconds after it arrives, so `useDeleteJournal` deliberately skips its
 * error toast for this one code and the dialog stays open instead.
 *
 * **The steer toward cancelling names a control.** "Cancel the journal
 * instead" is only actionable if the user knows where the cancelled state
 * lives, and it lives in the event editor's *Event Status* select — a
 * type-data edit rather than an operation of its own. A journal with no
 * `EVENT` type has no cancelled state at all, so it is told that plainly
 * rather than pointed at a control it does not have.
 *
 * **The blockers are read through `blockingTasksFrom`, never off `meta`.** A
 * payload missing a field a link needs falls back to the ordinary toast, so a
 * malformed refusal degrades to today's behaviour instead of rendering an
 * explanation with a dead link in it.
 *
 * One case earns a control rather than a link: a task created **and** due in
 * this journal is anchored to it twice, so `action_anchor_for` resolves to the
 * creating journal, which is this same one. The payload is right — the deletion
 * was refused, so the journal is still there — but a link to the route already
 * open would change nothing and leave the dialog covering the very controls it
 * points at. That row offers to close instead, because closing *is* the
 * navigation: the task's own actions are on the page underneath. Every other
 * row closes on its way out too, so no overlay outlives the page it was on.
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Trash2 } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { blockingTasksFrom, useDeleteJournal } from '@/lib/api/journals';
import { statusWording } from '@/lib/task-display';
import { JournalType, type BlockingTask, type Journal } from '@/types/journals';
import type { TaskAnchorRole } from '@/types/journals';

interface DeleteJournalDialogProps {
  /** The journal the delete would remove. */
  readonly journal: Journal;
}

const ROLE_WORDS: Record<TaskAnchorRole, string> = {
  creating: 'created in this journal',
  due: 'due in this journal',
};

/**
 * Why one task blocks the deletion.
 *
 * A task anchored to this journal twice — created here *and* due here — is one
 * blocker with two roles, so the two are joined rather than listed as separate
 * rows. The backend sorts them "creating" before "due", and that order is kept.
 */
function describeRoles(roles: readonly TaskAnchorRole[]): string {
  return roles.map(role => ROLE_WORDS[role] ?? role).join(' and ');
}

export function DeleteJournalDialog({ journal }: DeleteJournalDialogProps) {
  const router = useRouter();
  const deleteJournal = useDeleteJournal();

  const [open, setOpen] = useState(false);
  const [blockers, setBlockers] = useState<BlockingTask[] | null>(null);

  const isEvent = journal.types?.includes(JournalType.EVENT) ?? false;

  /**
   * Every close the **user** asks for, refused while the delete is in flight.
   *
   * The request has already left and closing cannot call it back, so a dialog
   * that vanished and then navigated away a moment later would be acting on a
   * decision the user had just withdrawn. Reopening starts from the
   * confirmation again rather than from a list of blockers that may since have
   * been cleared.
   */
  const handleOpenChange = (next: boolean) => {
    if (next) {
      setBlockers(null);
      setOpen(true);
      return;
    }
    if (deleteJournal.isPending) return;
    setOpen(false);
    setBlockers(null);
  };

  const send = () => {
    deleteJournal.mutate(journal.id, {
      onSuccess: () => {
        setOpen(false);
        setBlockers(null);
        router.push('/journals');
      },
      onError: error => {
        // `null` covers every refusal that is not this one — a different code,
        // a body without usable blockers — and each of those has already been
        // reported by the hook's toast, so the dialog gets out of the way.
        const refused = blockingTasksFrom(error);
        if (!refused) {
          setOpen(false);
          return;
        }
        setBlockers(refused);
      },
    });
  };

  const steer = isEvent ? (
    <>
      Cancelling this event keeps it, and any tasks anchored to it, intact — set{' '}
      <strong>Event Status</strong> to <strong>Cancelled</strong> in the Event
      section of this page instead of deleting it.
    </>
  ) : (
    <>
      This journal has <strong>no cancelled state</strong> — only event journals
      have one — so there is nothing to cancel in its place. Anything anchored
      to it has to be actioned from its own journal first.
    </>
  );

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          aria-label='Delete journal'
          disabled={deleteJournal.isPending}
          data-testid='delete-journal-button'
          className='text-destructive hover:bg-destructive/10'
        >
          <Trash2 className='h-4 w-4' aria-hidden='true' />
        </Button>
      </AlertDialogTrigger>

      <AlertDialogContent data-testid='delete-journal-dialog'>
        {blockers ? (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>
                This journal can’t be deleted yet
              </AlertDialogTitle>
              <AlertDialogDescription>
                {blockers.length === 1
                  ? 'One task is anchored to this journal, and a task can never exist without both of its journals. Complete, cancel or retarget it, then delete again.'
                  : `${blockers.length} tasks are anchored to this journal, and a task can never exist without both of its journals. Complete, cancel or retarget them, then delete again.`}
              </AlertDialogDescription>
            </AlertDialogHeader>

            <ul
              className='space-y-3 text-sm'
              data-testid='journal-delete-blockers'
            >
              {blockers.map(task => (
                <li
                  key={task.task_id}
                  className='border-border rounded-md border p-3'
                  data-testid={`journal-delete-blocker-${task.task_id}`}
                >
                  <div className='font-medium'>{task.text}</div>
                  <div className='text-muted-foreground mt-1'>
                    {statusWording(task.status)} ·{' '}
                    {describeRoles(task.blocking_roles)}
                  </div>
                  {String(task.action_journal_id) === journal.id ? (
                    <button
                      type='button'
                      className='text-primary mt-1 inline-block underline underline-offset-4'
                      data-testid={`journal-delete-blocker-link-${task.task_id}`}
                      onClick={() => handleOpenChange(false)}
                    >
                      Action it on this journal
                    </button>
                  ) : (
                    <Link
                      href={`/journals/${task.action_journal_id}`}
                      className='text-primary mt-1 inline-block underline underline-offset-4'
                      data-testid={`journal-delete-blocker-link-${task.task_id}`}
                      onClick={() => handleOpenChange(false)}
                    >
                      {task.action_journal_title}
                    </Link>
                  )}
                </li>
              ))}
            </ul>

            <p
              className='text-muted-foreground text-sm'
              data-testid='delete-journal-steer'
            >
              {steer}
            </p>

            <AlertDialogFooter>
              <AlertDialogCancel>Close</AlertDialogCancel>
              <Button
                type='button'
                variant='destructive'
                disabled={deleteJournal.isPending}
                data-testid='retry-delete-journal'
                onClick={send}
              >
                Try again
              </Button>
            </AlertDialogFooter>
          </>
        ) : (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete this journal?</AlertDialogTitle>
              <AlertDialogDescription>
                Deleting “{journal.title}” is permanent and takes its content,
                tags and relationships with it.
              </AlertDialogDescription>
            </AlertDialogHeader>

            <p
              className='text-muted-foreground text-sm'
              data-testid='delete-journal-steer'
            >
              {steer}
            </p>

            <AlertDialogFooter>
              <AlertDialogCancel>Keep journal</AlertDialogCancel>
              <Button
                type='button'
                variant='destructive'
                disabled={deleteJournal.isPending}
                data-testid='confirm-delete-journal'
                onClick={send}
              >
                Delete journal
              </Button>
            </AlertDialogFooter>
          </>
        )}
      </AlertDialogContent>
    </AlertDialog>
  );
}
