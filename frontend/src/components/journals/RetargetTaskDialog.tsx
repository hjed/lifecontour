/**
 * Moves a task onto a new due journal — and so resurrects a lapsed or
 * cancelled one, and reopens a done one.
 *
 * One endpoint, four things to ask for. The specification treats extending a
 * deadline, meeting a lapsed commitment again, bringing a cancelled task back
 * (its **only** exit, since the service refuses both status calls out of
 * cancelled) and reopening a completed task as different acts, so the trigger,
 * the heading and the explanation are worded per case in `lib/task-display.ts`
 * rather than here.
 *
 * **The reopen confirmation is the server's refusal, not a client-side
 * prediction.** A done task's retarget is sent without the acknowledgement,
 * refused with `TASK_REOPEN_NOT_ACKNOWLEDGED` — a 409 that writes nothing, and
 * that `useRetargetTask` deliberately does not toast because it is a question
 * rather than a failure — and only then confirmed and re-sent with
 * `acknowledge_reopen`. Predicting it here would be a second copy of the
 * service's rule, free to drift from it; worse, it would sit *ahead* of the
 * future-date check, so a user retargeting a done task onto a past journal
 * would be asked to confirm a request that was never going to succeed. The
 * service checks the acknowledgement last for exactly that reason.
 *
 * **A rejected journal is reported against the field, not only in a toast.**
 * The picker judges "future" against the timezone the browser can see; the
 * server judges it against the user's *configured* zone, and when the two
 * disagree the server is right. `TASK_DUE_JOURNAL_NOT_FUTURE` therefore lands
 * on the due-journal field through `form.setError`, and focus moves back to
 * it. The toast `useRetargetTask` raises is left alone: it is the only report
 * a user who has scrolled away would get, and suppressing it would widen an
 * exception written for one refusal into a rule about all of them.
 */

'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { CalendarClock } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
} from '@/components/ui/form';
import { FutureJournalPicker } from '@/components/journals/FutureJournalPicker';
import {
  TASK_DUE_JOURNAL_NOT_FUTURE,
  TASK_REOPEN_NOT_ACKNOWLEDGED,
  TaskApiError,
  useRetargetTask,
} from '@/lib/api/tasks';
import { formatFutureJournalDate } from '@/lib/future-journals';
import type { FutureJournalOption } from '@/lib/future-journals';
import { retargetAction } from '@/lib/task-display';
import type { JournalTaskResource } from '@/types/tasks';

/**
 * The chosen journal, carried whole rather than as a bare id.
 *
 * The confirmation step has to name the journal and its date back to the user
 * before the reopen, and a form holding only an id would have to look it up in
 * a list the picker owns and may have searched away from.
 */
const dueJournalSchema = z.object({
  id: z.string(),
  title: z.string(),
  date: z.string(),
  startsAt: z.string(),
  cancelled: z.boolean(),
});

/**
 * `superRefine` rather than `refine`, deliberately: `refine` would narrow the
 * schema's *output* away from `null` while its input kept it, which leaves
 * react-hook-form with two different shapes for one field. The requirement is
 * the same either way — a journal must be chosen — and this states it without
 * splitting the type.
 */
const retargetSchema = z.object({
  dueJournal: dueJournalSchema.nullable().superRefine((journal, ctx) => {
    if (journal === null) {
      ctx.addIssue({
        code: 'custom',
        message: 'Choose the journal this task should be due in.',
      });
    }
  }),
});

type RetargetFormValues = z.infer<typeof retargetSchema>;

export interface RetargetTaskDialogProps {
  /** The task being moved. */
  readonly task: JournalTaskResource;
  /**
   * Whether the trigger is locked out — the row's "one write at a time per
   * task" guard, which the actions group owns.
   */
  readonly disabled?: boolean;
}

/**
 * The picker, wired to the form field it serves.
 *
 * Not wrapped in `FormControl`: that clones its `id`, `aria-describedby` and
 * `aria-invalid` onto the child's root element, which here is the picker's
 * container rather than its input. The three are passed to the input
 * explicitly instead, which is what the picker's props exist for.
 */
function DueJournalField({
  inputId,
  value,
  onSelect,
  currentDueJournalId,
  disabled,
}: {
  readonly inputId: string;
  readonly value: FutureJournalOption | null;
  readonly onSelect: (journal: FutureJournalOption) => void;
  readonly currentDueJournalId: string;
  readonly disabled: boolean;
}) {
  const { error, formMessageId } = useFormField();

  return (
    <FutureJournalPicker
      inputId={inputId}
      value={value}
      onSelect={onSelect}
      currentDueJournalId={currentDueJournalId}
      disabled={disabled}
      invalid={Boolean(error)}
      describedById={error ? formMessageId : undefined}
    />
  );
}

export function RetargetTaskDialog({
  task,
  disabled = false,
}: RetargetTaskDialogProps) {
  const { status, lapsed, text, due_journal } = task.attributes;
  const offer = retargetAction(status, lapsed);

  const [open, setOpen] = useState(false);
  const [awaitingReopenConfirmation, setAwaitingReopenConfirmation] =
    useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);

  const dueJournalInputId = `${useId()}-due-journal`;
  const focusPicker = () => document.getElementById(dueJournalInputId)?.focus();

  const form = useForm<RetargetFormValues>({
    resolver: zodResolver(retargetSchema),
    defaultValues: { dueJournal: null },
  });
  // `useWatch` rather than `form.watch`: the subscription form is the one the
  // React Compiler can follow, and `watch` makes it skip this component
  // wholesale.
  const chosen = useWatch({ control: form.control, name: 'dueJournal' });

  const retarget = useRetargetTask();

  // The one effect here, and it is focus's own. Each of the three moments
  // that decide where focus belongs — the dialog opening, the reopen gate
  // appearing, and it being declined — swaps which half of the dialog is
  // mounted, so a click handler calling `focus()` would be reaching for an
  // element React has not rendered yet. Running after the render is what makes
  // the target exist.
  useEffect(() => {
    if (!open) return;
    if (awaitingReopenConfirmation) {
      confirmRef.current?.focus();
    } else {
      document.getElementById(dueJournalInputId)?.focus();
    }
  }, [awaitingReopenConfirmation, open, dueJournalInputId]);

  /**
   * Close and forget what was being chosen.
   *
   * Radix calls `onOpenChange` when *it* closes the dialog — Escape, the
   * overlay, the close button — but not when a controlled `open` is set to
   * false from inside, so a successful move has to come through here rather
   * than setting the flag directly or the reset never runs: reopening would
   * restore the journal already chosen and, worse, drop the user straight back
   * into a reopen confirmation they had already resolved.
   */
  const resetAndClose = () => {
    setOpen(false);
    setAwaitingReopenConfirmation(false);
    form.reset({ dueJournal: null });
  };

  /**
   * Every close the **user** asks for, and it is refused while a write is in
   * flight.
   *
   * The request has already left; closing cannot call it back, so a dialog
   * that vanished on Cancel and then toasted "Task moved" a second later would
   * be reporting the opposite of what the user just asked for. Holding it open
   * for the moment the write takes is the honest version, and it is the same
   * "one write at a time" stance the row's buttons already take.
   *
   * Aborting the request instead was considered and rejected: a `POST` that
   * has reached the server may already have committed, so cancelling it
   * client-side would make the UI's claim *less* true rather than more.
   *
   * The success path deliberately does not come through here — it calls
   * `resetAndClose` directly, because at that point there is nothing left to
   * protect and `isPending` may not yet have settled in this closure.
   */
  const handleOpenChange = (next: boolean) => {
    if (next) {
      setOpen(true);
      return;
    }
    if (retarget.isPending) return;
    resetAndClose();
  };

  const closeDialog = () => handleOpenChange(false);

  const send = (journal: FutureJournalOption, acknowledgeReopen: boolean) => {
    retarget.mutate(
      {
        taskId: task.id,
        due_journal_id: Number(journal.id),
        acknowledge_reopen: acknowledgeReopen,
      },
      {
        onSuccess: resetAndClose,
        onError: error => {
          if (
            error instanceof TaskApiError &&
            error.code === TASK_REOPEN_NOT_ACKNOWLEDGED
          ) {
            setAwaitingReopenConfirmation(true);
            return;
          }

          // Every other outcome goes back to the picker, and the confirmation
          // step is the reason this is unconditional rather than only for the
          // rejection below. A *confirmed* reopen that fails would otherwise
          // leave the user on a panel offering one button that has just been
          // refused, with the explanation rendered behind it where the picker
          // is not mounted — the one path in this dialog that could strand
          // someone. Clearing it also brings focus back, through the effect
          // above.
          setAwaitingReopenConfirmation(false);

          if (
            error instanceof TaskApiError &&
            error.code === TASK_DUE_JOURNAL_NOT_FUTURE
          ) {
            form.setError('dueJournal', {
              type: 'server',
              message: error.message,
            });
            focusPicker();
          }
          // Anything else has already been reported by the hook's toast, and
          // the dialog stays open so the choice can be tried again.
        },
      }
    );
  };

  const onSubmit = (values: RetargetFormValues) => {
    if (!values.dueJournal) return;
    send(values.dueJournal, false);
  };

  const declineReopen = () => setAwaitingReopenConfirmation(false);

  // `disabled` already carries the row's "one write at a time per task" guard,
  // which reads the mutation cache rather than this component; subscribing to
  // it again here would be a second subscription per row saying the same thing.
  const busy = disabled || retarget.isPending;

  // Re-checked against the **live** task rather than the snapshot taken when
  // the journal was picked. A concurrent refresh elsewhere can make the chosen
  // journal the one the task is already due in, and the service treats naming
  // that journal as a no-op: a 200 that moved nothing, reported as a move, and
  // for a done task a reopen that never happened. The picker refuses it at
  // selection time; this is the same rule re-read at submit time, where the
  // task's own due journal is a prop and therefore current.
  const chosenIsAlreadyDue =
    chosen != null && chosen.id === String(due_journal.id);
  const canSubmit = chosen != null && !chosenIsAlreadyDue && !busy;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          aria-label={offer.accessibleName}
          disabled={disabled}
          data-testid='journal-task-action-retarget'
        >
          <CalendarClock aria-hidden='true' />
          {offer.label}
        </Button>
      </DialogTrigger>

      <DialogContent
        className='sm:max-w-xl'
        // Radix's default focuses the first tabbable node, which happens to be
        // the search box today. Saying so is better than depending on it: a
        // control added above the picker later would move focus silently, and
        // this is also the hook that stops Radix and the effect below racing
        // for the same element.
        onOpenAutoFocus={event => {
          event.preventDefault();
          focusPicker();
        }}
      >
        <DialogHeader>
          <DialogTitle>{offer.dialogTitle}</DialogTitle>
          <DialogDescription>{offer.dialogDescription}</DialogDescription>
        </DialogHeader>

        <p
          className='bg-muted text-foreground rounded-md px-3 py-2 text-sm'
          data-testid='retarget-task-text'
        >
          {text}
        </p>

        {awaitingReopenConfirmation && chosen ? (
          <div className='space-y-4' data-testid='retarget-reopen-confirm'>
            <p className='text-sm'>
              This task is marked done. Making it due in{' '}
              <strong>{chosen.title}</strong> on{' '}
              {formatFutureJournalDate(chosen.date)} reopens it as not done.
              Nothing has been changed yet.
            </p>
            <DialogFooter>
              {/* Locked with its twin while the acknowledged write is in
                  flight: declining cannot recall a request that has already
                  left, so an enabled "Keep it done" would promise something it
                  cannot deliver — the same reason Cancel and Escape are
                  refused a moment earlier. */}
              <Button
                type='button'
                variant='outline'
                onClick={declineReopen}
                disabled={busy}
                data-testid='retarget-reopen-decline'
              >
                Keep it done
              </Button>
              <Button
                ref={confirmRef}
                type='button'
                disabled={!canSubmit}
                onClick={() => send(chosen, true)}
                data-testid='retarget-reopen-accept'
              >
                Reopen and move task
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className='space-y-4'
              noValidate
            >
              <FormField
                control={form.control}
                name='dueJournal'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel htmlFor={dueJournalInputId}>
                      Journal this task is due in
                    </FormLabel>
                    <DueJournalField
                      inputId={dueJournalInputId}
                      value={field.value}
                      onSelect={journal => field.onChange(journal)}
                      currentDueJournalId={String(due_journal.id)}
                      disabled={busy}
                    />
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* The model's one automatic link, and it applies to every case
                  rather than only to a deferral, so it is stated here rather
                  than in one of the four per-case descriptions. */}
              <p
                className='text-muted-foreground text-sm'
                data-testid='retarget-keeps-previous'
              >
                The journal this task is leaving is kept on it as a mention, so
                the trail of a deferred commitment stays visible.
              </p>

              <DialogFooter>
                <Button
                  type='button'
                  variant='outline'
                  onClick={closeDialog}
                  disabled={busy}
                  data-testid='retarget-dialog-cancel'
                >
                  Cancel
                </Button>
                <Button
                  type='submit'
                  disabled={!canSubmit}
                  data-testid='retarget-dialog-submit'
                >
                  {offer.submitLabel}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
