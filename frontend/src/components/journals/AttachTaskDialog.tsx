/**
 * Mentions an existing task in the journal being viewed.
 *
 * One of the two deliberate acts the specification names — "a link is created
 * when the user deliberately attaches an existing task to the journal they are
 * viewing, or links a journal to a task from the task itself" — and the only
 * one this product has a surface for, since tasks have no route of their own.
 *
 * **The picker names a journal before it names a task, and that is the whole
 * design.** The criterion is that it be "scoped and searchable rather than
 * listing every task ... this affordance must not become one", and the scoping
 * here is structural rather than a limit imposed on an unbounded list: there is
 * no endpoint that lists or searches tasks across journals, and this phase does
 * not add one. What exists is `GET /api/journals/{id}/tasks`, so the user finds
 * the journal the task is on — the journal where it is due, was created, or was
 * last discussed — and picks it out of that journal's own listing. The reverse
 * shape, a task search narrowed by journal, would be the global task list the
 * specification refuses, wearing a filter.
 *
 * Two exclusions keep the server's refusals off the screen: the journal being
 * viewed cannot be its own source, and a task already linked here is not
 * offered. Both are computed from a cache that can be stale, which is why the
 * 409 is still rendered against the field rather than trusted away.
 */

'use client';

import { useId, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Link2 } from 'lucide-react';

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
  FormMessage,
  useFormField,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { JournalSearchCombobox } from '@/components/journals/JournalSearchCombobox';
import {
  TASK_JOURNAL_IS_ANCHOR,
  TaskApiError,
  useAttachTaskIntermediateJournal,
  useJournalTasks,
} from '@/lib/api/tasks';
import { statusWording } from '@/lib/task-display';
import type { JournalTaskResource } from '@/types/tasks';

/**
 * Only the id is written, but the whole task is held.
 *
 * The chosen option has to keep its text on screen while the filter moves
 * underneath it, and a form holding a bare id would have to find it again in a
 * list the filter may have narrowed away.
 */
const attachSchema = z.object({
  task: z
    .object({ id: z.string(), text: z.string() })
    .nullable()
    .superRefine((task, ctx) => {
      if (task === null) {
        ctx.addIssue({
          code: 'custom',
          message: 'Choose the task to mention in this journal.',
        });
      }
    }),
});

type AttachFormValues = z.infer<typeof attachSchema>;

export interface AttachTaskDialogProps {
  /** The journal being viewed — the one the mention is attached to. */
  readonly journalId: string;
  /**
   * Every task already linked to this journal, in any role.
   *
   * Passed down from the listing the section has already read rather than
   * fetched again here: the section is rendering those tasks as this dialog
   * opens, so a second query would ask a question already answered.
   */
  readonly linkedTaskIds: readonly string[];
}

/** What a chosen task carries between the picker and the write. */
interface ChosenTask {
  readonly id: string;
  readonly text: string;
}

/**
 * The task options, wired to the form field they serve.
 *
 * Named through `aria-labelledby` rather than a `FormLabel`, because a
 * `<label>` cannot name a `radiogroup` — it is not a labelable element, so the
 * `htmlFor` would point at nothing. **And through a plain `<span>` rather than
 * a `<fieldset>`/`<legend>`:** a fieldset carries an implicit `role="group"`
 * named by its legend, so wrapping the radio group in one and *also* pointing
 * the group at that legend gives two nested groups with the same name, which a
 * screen reader reads out twice. The disabling a fieldset would have done for
 * free is passed to each option instead.
 */
function TaskChoiceField({
  tasks,
  value,
  onChoose,
  disabled,
}: {
  readonly tasks: readonly JournalTaskResource[];
  readonly value: ChosenTask | null;
  readonly onChoose: (task: ChosenTask) => void;
  readonly disabled: boolean;
}) {
  const { error, formMessageId } = useFormField();
  const labelId = `${useId()}-task-choice`;
  const optionPrefix = useId();

  return (
    <div className='space-y-2'>
      <span id={labelId} className='block text-sm leading-none font-medium'>
        Task to attach
      </span>
      <RadioGroup
        aria-labelledby={labelId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? formMessageId : undefined}
        value={value?.id ?? ''}
        onValueChange={id => {
          const task = tasks.find(candidate => candidate.id === id);
          if (task) onChoose({ id: task.id, text: task.attributes.text });
        }}
        className='max-h-64 gap-2 overflow-y-auto'
      >
        {tasks.map(task => {
          const optionId = `${optionPrefix}-${task.id}`;
          const { text, status, due_journal } = task.attributes;

          return (
            <div
              key={task.id}
              className='border-border flex items-start gap-3 rounded-md border p-3'
            >
              <RadioGroupItem
                value={task.id}
                id={optionId}
                disabled={disabled}
                className='mt-1'
              />
              <Label
                htmlFor={optionId}
                className='flex flex-col items-start gap-1'
              >
                <span className='font-medium'>{text}</span>
                <span className='text-muted-foreground text-xs font-normal'>
                  {statusWording(status)} · due in {due_journal.title}
                </span>
              </Label>
            </div>
          );
        })}
      </RadioGroup>
    </div>
  );
}

export function AttachTaskDialog({
  journalId,
  linkedTaskIds,
}: AttachTaskDialogProps) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<{ id: string; title: string } | null>(
    null
  );
  const [filter, setFilter] = useState('');
  /**
   * What the journal search box holds, owned here rather than derived from the
   * chosen journal.
   *
   * `JournalSearchCombobox` re-syncs its own input whenever its `value` prop
   * changes, so a `value` computed as `source?.title ?? ''` throws away the
   * very keystroke that put the journal down: type `B` over a chosen "Trip
   * planning" and the callback clears `source`, `value` becomes `''`, and the
   * `B` goes with it — leaving the user searching for `each` after typing
   * `Beach`. Tracking exactly what was typed keeps the prop and the input in
   * agreement, so the sync is a no-op instead of a rewind.
   */
  const [journalQuery, setJournalQuery] = useState('');

  const journalInputId = `${useId()}-source-journal`;
  const filterInputId = `${useId()}-task-filter`;

  const form = useForm<AttachFormValues>({
    resolver: zodResolver(attachSchema),
    defaultValues: { task: null },
  });
  // `useWatch` rather than `form.watch`, which makes the React Compiler skip
  // this component wholesale.
  const chosen = useWatch({ control: form.control, name: 'task' });

  const attach = useAttachTaskIntermediateJournal();

  // The hook is disabled on an empty id, so nothing is requested until a
  // journal has been named. That is the criterion, enforced by the query rather
  // than by a branch around the render.
  const {
    data,
    isLoading: listingLoading,
    isError: listingFailed,
  } = useJournalTasks(source?.id ?? '');

  // Focus on open, stated rather than inherited. Radix's default lands on the
  // first tabbable node, which is the search box only until something is added
  // above it, and saying so also stops a later effect and Radix racing for the
  // same element — the shape Phase 18 had to untangle in the retarget dialog.
  // One panel, so `onOpenAutoFocus` is the whole of it and no effect is needed.
  const focusJournalSearch = () =>
    document.getElementById(journalInputId)?.focus();

  /**
   * Whether the journal search has a dropdown open, asked of the DOM.
   *
   * **Escape belongs to whichever thing is open.** The combobox closes its own
   * results on Escape and lets the key carry on, and Radix's dismissable layer
   * listens on `document` in the *capture* phase — so one press would dismiss a
   * dropdown and throw the dialog away with it, losing the journal, the filter
   * and the chosen task. A React handler cannot get in front of a capture
   * listener on `document`, so the interception has to be Radix's own
   * `onEscapeKeyDown`, and the state it needs is the one the combobox already
   * publishes on its input.
   */
  const searchDropdownIsOpen = () =>
    document.getElementById(journalInputId)?.getAttribute('aria-expanded') ===
    'true';

  const resetAndClose = () => {
    setOpen(false);
    setSource(null);
    setFilter('');
    setJournalQuery('');
    form.reset({ task: null });
  };

  /**
   * Every close the **user** asks for, refused while the write is in flight.
   *
   * The `POST` has already left and cannot be recalled — aborting it would make
   * the UI's claim less true rather than more, since a request that reached the
   * server may already have committed — so a dialog that vanished on Cancel and
   * then toasted "Journal linked" a second later would report the opposite of
   * what the user had just asked for. The success path calls `resetAndClose`
   * directly, where there is nothing left to protect.
   */
  const handleOpenChange = (next: boolean) => {
    if (next) {
      setOpen(true);
      return;
    }
    if (attach.isPending) return;
    resetAndClose();
  };

  /**
   * Narrow the options, and drop a choice the narrowing has hidden.
   *
   * Leaving it selected would arm the submit button over a task no longer on
   * screen — the dialog would be about to mention something the user could not
   * see it was about to mention.
   */
  const applyFilter = (next: string) => {
    setFilter(next);
    const search = next.trim().toLowerCase();
    if (chosen && search && !chosen.text.toLowerCase().includes(search)) {
      form.setValue('task', null);
    }
  };

  const chooseSource = (journal: { id: string; title: string }) => {
    setSource(journal);
    setFilter('');
    form.reset({ task: null });
  };

  /**
   * Put the chosen journal down, along with everything picked out of it.
   *
   * **Typing over the journal abandons it**, and the combobox does not say so
   * on its own: it reports `onClear` only when the input goes fully *empty*, so
   * editing "Trip planning" into "Beach" would leave the field showing one
   * journal while the list underneath still held the other one's tasks — and a
   * task could be attached from a source the user believed they had moved off.
   * `onSearchChange` fires on user input alone and never on a selection, which
   * is what makes it safe to compare against the chosen title here.
   */
  const forgetSource = () => {
    setSource(null);
    setFilter('');
    form.reset({ task: null });
  };

  /** Put the journal down *and* empty the box, which is what clearing means. */
  const clearJournalSearch = () => {
    setJournalQuery('');
    forgetSource();
  };

  const onSubmit = (values: AttachFormValues) => {
    if (!values.task) return;

    attach.mutate(
      { taskId: values.task.id, journalId },
      {
        onSuccess: resetAndClose,
        onError: error => {
          if (
            error instanceof TaskApiError &&
            error.code === TASK_JOURNAL_IS_ANCHOR
          ) {
            // The exclusion above judged this task from a cache, and the cache
            // can be stale: a task retargeted onto this journal elsewhere is an
            // anchor here by the time the request lands. The server is the
            // authority, so its refusal lands on the field the choice was made
            // in. The hook's toast is left alone — a user who has scrolled
            // would otherwise get no report at all.
            form.setError('task', { type: 'server', message: error.message });
          }
          // Every other outcome has been reported by that toast, and the dialog
          // stays open so the choice can be tried again. Focus is not moved for
          // either: there is no focusable element carrying the message — a
          // `radiogroup` is not one, and its options are reached through a
          // roving tabindex — and Sonner's toaster is already a polite live
          // region, so the refusal is spoken without one.
        },
      }
    );
  };

  // Tasks the journal being viewed already holds in some role are dropped: one
  // already mentioned here would be a no-op, and one anchored here is a 409.
  const available = (data?.data ?? []).filter(
    task => !linkedTaskIds.includes(task.id)
  );
  const needle = filter.trim().toLowerCase();
  const options = needle
    ? available.filter(task =>
        task.attributes.text.toLowerCase().includes(needle)
      )
    : available;

  /**
   * One line saying what the picker currently holds.
   *
   * Every state of the option list says something, including the ordinary one:
   * a `role="status"` that only spoke up on failure would leave a screen-reader
   * user with a list that had silently changed under a filter.
   */
  const situation = (): string => {
    if (!source) return 'Find the journal the task is on to choose from it.';
    if (listingLoading) return 'Loading that journal’s tasks…';
    if (listingFailed) return 'That journal’s tasks could not be loaded.';
    if ((data?.data.length ?? 0) === 0)
      return `${source.title} has no tasks on it.`;
    if (available.length === 0)
      return `Every task on ${source.title} is already linked to this journal.`;
    if (options.length === 0) return 'No tasks match that filter.';
    return options.length === 1
      ? '1 task to choose from.'
      : `${options.length} tasks to choose from.`;
  };

  const busy = attach.isPending;

  // Re-read against what is **currently** offered rather than against what was
  // offered when the choice was made. `linkedTaskIds` is a prop: a write
  // elsewhere on the page can refresh the journal's listing under an open
  // dialog and make the chosen task one this journal already holds, and the
  // source journal's own listing can refetch without it. Either way the choice
  // is no longer on the list it was picked from, and submitting it would send a
  // request this dialog exists to keep off the wire. The filter's own clearing
  // (above) covers the visible half of the same rule; this covers the half the
  // user cannot see happening.
  const chosenStillOffered =
    chosen != null && options.some(option => option.id === chosen.id);
  const canSubmit = chosenStillOffered && !busy;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          data-testid='journal-tasks-attach'
        >
          <Link2 aria-hidden='true' />
          Attach task
        </Button>
      </DialogTrigger>

      <DialogContent
        className='sm:max-w-xl'
        onOpenAutoFocus={event => {
          event.preventDefault();
          focusJournalSearch();
        }}
        // Two reasons to refuse an Escape, and they are different refusals: a
        // press that belongs to the open dropdown, and a press over a write
        // that has already left. The second is the guard `handleOpenChange`
        // applies to every close; this one is about which control the key was
        // meant for, so a second press — with no dropdown open — still closes
        // the dialog as a keyboard user expects.
        onEscapeKeyDown={event => {
          if (searchDropdownIsOpen()) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>Attach an existing task</DialogTitle>
          <DialogDescription>
            Mention a task from another journal in this one. The task keeps its
            own due and creating journals; this only records that it came up
            here.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className='space-y-4'
            noValidate
          >
            <div className='space-y-2'>
              <Label htmlFor={journalInputId}>Journal the task is on</Label>
              <JournalSearchCombobox
                inputId={journalInputId}
                placeholder='Search journals by title'
                excludeJournalId={journalId}
                value={journalQuery}
                disabled={busy}
                onSelect={journal => {
                  setJournalQuery(journal.attributes.title);
                  chooseSource({
                    id: journal.id,
                    title: journal.attributes.title,
                  });
                }}
                onSearchChange={query => {
                  setJournalQuery(query);
                  if (source && query !== source.title) forgetSource();
                }}
                onClear={clearJournalSearch}
              />
            </div>

            {source && available.length > 0 && (
              <div className='space-y-2'>
                <Label htmlFor={filterInputId}>Filter tasks</Label>
                <Input
                  id={filterInputId}
                  type='text'
                  autoComplete='off'
                  placeholder={`Narrow ${source.title}’s tasks`}
                  value={filter}
                  disabled={busy}
                  onChange={event => applyFilter(event.target.value)}
                />
              </div>
            )}

            <p
              role='status'
              className='text-muted-foreground text-sm'
              data-testid='attach-dialog-situation'
            >
              {situation()}
            </p>

            {/* Mounted as soon as a journal is named, not only when there are
                options: a server refusal is written onto this field, and if
                the option list had emptied between the submit and the 409
                arriving — a refetch, or another surface linking the task here
                — `FormMessage` would not be in the document to receive it, and
                only the toast would survive. */}
            {source && (
              <FormField
                control={form.control}
                name='task'
                render={({ field }) => (
                  <FormItem>
                    {options.length > 0 && (
                      <TaskChoiceField
                        tasks={options}
                        value={field.value}
                        onChoose={task => field.onChange(task)}
                        disabled={busy}
                      />
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                onClick={() => handleOpenChange(false)}
                disabled={busy}
                data-testid='attach-dialog-cancel'
              >
                Cancel
              </Button>
              <Button
                type='submit'
                disabled={!canSubmit}
                data-testid='attach-dialog-submit'
              >
                Attach to this journal
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
