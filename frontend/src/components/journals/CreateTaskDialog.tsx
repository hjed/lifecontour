/**
 * The journal page's *New task* button and the dialog it opens.
 *
 * The form, and every rule of the specification's *Creating a task*, is
 * `CreateTaskForm`. This file owns only what being a dialog adds:
 *
 * - **Each opening starts empty.** Radix unmounts the content on close, and
 *   the form is keyed per opening as well, so a reopen during the exit
 *   animation does not bring back the last task's text, journal or refusal.
 * - **No close while a write is in flight.** The request has already left and
 *   may have committed, so a dialog that vanished on Cancel and then toasted
 *   "Task created" would report the opposite of what the user asked for. The
 *   form reports busy before its request leaves, and the guard reads a ref so
 *   an Escape in the same tick cannot slip past it.
 */

'use client';

import { useRef, useState } from 'react';
import { Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { CreateTaskForm } from '@/components/tasks/CreateTaskForm';

export interface CreateTaskDialogProps {
  /** The journal being viewed, which becomes the task's creating journal. */
  readonly journalId: string;
}

export function CreateTaskDialog({ journalId }: CreateTaskDialogProps) {
  const [open, setOpen] = useState(false);
  const [opening, setOpening] = useState(0);
  // The ref is what the close guard reads; the state only redraws the X.
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);

  const reportBusy = (next: boolean) => {
    busyRef.current = next;
    setBusy(next);
  };

  /** Every close the **user** asks for, refused while a write is in flight. */
  const handleOpenChange = (next: boolean) => {
    if (next) {
      reportBusy(false);
      setOpening(current => current + 1);
      setOpen(true);
      return;
    }
    if (busyRef.current) return;
    setOpen(false);
  };

  /**
   * A successful create closes unconditionally: its success arrives before
   * the form reports the write settled, so the guard would still refuse it.
   */
  const closeCreated = () => {
    reportBusy(false);
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          type='button'
          size='sm'
          data-testid='journal-task-action-create'
        >
          <Plus aria-hidden='true' />
          New task
        </Button>
      </DialogTrigger>

      <DialogContent
        className='sm:max-w-xl'
        // Withdrawn while the write is outstanding, because `handleOpenChange`
        // refuses the close it would ask for: an X that stays put and does
        // nothing is a control lying about being live, and Cancel beside it is
        // already visibly disabled.
        showCloseButton={!busy}
        // The form focuses its text field itself (`autoFocusText`), before
        // Radix would; this only keeps Radix from second-guessing it.
        onOpenAutoFocus={event => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>New task</DialogTitle>
          <DialogDescription>
            The commitment is recorded in this journal and comes due in a
            journal you choose.
          </DialogDescription>
        </DialogHeader>

        <CreateTaskForm
          key={opening}
          creatingJournal={{ kind: 'fixed', id: journalId }}
          onCreated={closeCreated}
          onCancel={() => handleOpenChange(false)}
          onBusyChange={reportBusy}
          autoFocusText
        />
      </DialogContent>
    </Dialog>
  );
}
