/**
 * Creates a task in the journal it arose in.
 *
 * The form on its own, so any host can mount it: `CreateTaskDialog` on the
 * journal page today, the New dialog next. A host supplies the creating
 * journal and hears back through `onCreated`, `onCancel` and `onBusyChange`.
 *
 * The specification's *Creating a task* is four sentences and every one of
 * them is a rule this form keeps:
 *
 * - **The creating journal is the journal being viewed** and "is never chosen
 *   separately". It is not a field here because it is not a field on the wire
 *   either — `POST /api/journals/{id}/tasks` takes it from the path — so the
 *   only place the rule can be checked is the request.
 * - **The due journal is picked from the user's future journals.** Invariant 5
 *   is the heart of the model: a task must name a real moment the user has
 *   already planned, so there is no bare date picker here and no journal is
 *   created silently to hold a task. `FutureJournalPicker` is mounted
 *   unchanged from the phase that built it for the retarget dialog.
 * - **Contacts are optional**, and "no contacts" is the *absence* of the
 *   field rather than an empty list — the create attributes forbid extras, so
 *   an empty array would be a second way of saying the same thing.
 * - **A user with no future journals is told so and offered one to create.**
 *   That offer lives in the picker, so the retarget dialog has it too.
 *
 * **A rejected value is reported against the field that caused it.** The
 * future-date rule has a code of its own (`TASK_DUE_JOURNAL_NOT_FUTURE`);
 * everything else the domain refuses arrives as one `TASK_VALIDATION_ERROR`
 * naming its field in `meta`, which `taskValidationField` reads. A refusal
 * this form has no input for is left to the hook's toast rather than pinned to
 * a field at random — and the toast is kept in every case, because a user who
 * has scrolled away from a field would otherwise get no report at all.
 *
 * **Busy is reported before the request leaves**, not on the render after it.
 * A host that refuses to close during a save would otherwise have a moment in
 * which it closes over a write already on its way. Leaving reports idle, so a
 * host is never left locked by a form it no longer shows.
 */

'use client';

import { useEffect, useEffectEvent, useId } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DialogFooter } from '@/components/ui/dialog';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import { DueJournalFormField } from '@/components/journals/FutureJournalPicker';
import {
  CONTACT_NOT_FOUND,
  TASK_DUE_JOURNAL_NOT_FUTURE,
  TaskApiError,
  taskValidationField,
  useCreateTask,
} from '@/lib/api/tasks';
import { generateDisplayName } from '@/lib/utils';

/**
 * The chosen journal, carried whole rather than as a bare id — the same shape
 * the picker yields, so nothing has to be looked up again in a list the user
 * may have searched away from.
 */
const dueJournalSchema = z.object({
  id: z.string(),
  title: z.string(),
  date: z.string(),
  startsAt: z.string(),
  cancelled: z.boolean(),
});

/** A chosen contact: the id the request needs, and the name the badge shows. */
const contactSchema = z.object({
  id: z.string(),
  name: z.string(),
});

const createTaskSchema = z.object({
  text: z.string().trim().min(1, 'Say what needs doing.'),
  /**
   * `superRefine` rather than `refine`: `refine` would narrow the schema's
   * *output* away from `null` while its input kept it, leaving react-hook-form
   * with two shapes for one field.
   */
  dueJournal: dueJournalSchema.nullable().superRefine((journal, ctx) => {
    if (journal === null) {
      ctx.addIssue({
        code: 'custom',
        message: 'Choose the journal this task is due in.',
      });
    }
  }),
  contacts: z.array(contactSchema),
});

type CreateTaskFormValues = z.infer<typeof createTaskSchema>;

/**
 * Which form field each refusal belongs against.
 *
 * Only the fields this form actually has an input for. A refusal naming
 * anything else is left to the toast rather than pinned somewhere at random,
 * which is the difference between reporting a failure and mislabelling one.
 *
 * A `Map` rather than an object literal, because the key is a string the
 * **server** chose: a plain object would answer
 * `FIELD_FOR_VALIDATION_ERROR['constructor']` through its prototype with
 * something truthy, and hand `form.setError` a function as a field name.
 */
const FIELD_FOR_VALIDATION_ERROR = new Map<string, keyof CreateTaskFormValues>([
  ['text', 'text'],
  ['due_journal_id', 'dueJournal'],
]);

export interface CreateTaskFormProps {
  /**
   * The journal being viewed, which becomes the task's **creating** journal.
   * Never offered as a choice, and never sent in the body: the endpoint takes
   * it from its path.
   */
  readonly journalId: string;
  /** The task exists. Not called if the form has gone by the time it does. */
  readonly onCreated: () => void;
  /** The user abandoned the form. Nothing has been written. */
  readonly onCancel: () => void;
  /**
   * A save started (`true`) or settled (`false`). Reported before the request
   * leaves, and `false` again when the form unmounts.
   */
  readonly onBusyChange?: (busy: boolean) => void;
  /**
   * Put the cursor in the text field on mount. Opt-in, because a host that
   * keeps the form mounted while hidden must not have it take focus.
   */
  readonly autoFocusText?: boolean;
}

/**
 * The contact search, wired to the form field by hand: `ContactSearchCombobox`
 * owns its input, so it cannot sit inside `FormControl`.
 */
function ContactsField({
  inputId,
  chosen,
  onChoose,
  disabled,
}: {
  readonly inputId: string;
  readonly chosen: CreateTaskFormValues['contacts'];
  readonly onChoose: (contact: { id: string; name: string }) => void;
  readonly disabled: boolean;
}) {
  const { error, formDescriptionId, formMessageId } = useFormField();

  // Both, and in that order: the description is true whether or not the field
  // is in error, and `FormControl` — which this control cannot be wrapped in,
  // for the reason above — is what would otherwise have assembled the pair.
  const describedBy = [formDescriptionId, error ? formMessageId : null]
    .filter(Boolean)
    .join(' ');

  return (
    <ContactSearchCombobox
      inputId={inputId}
      placeholder='Search your contacts…'
      disabled={disabled}
      excludeContactIds={chosen.map(contact => contact.id)}
      describedById={describedBy}
      invalid={Boolean(error)}
      onSelect={contact =>
        onChoose({
          id: contact.id,
          name:
            generateDisplayName(
              contact.attributes.first_name,
              contact.attributes.last_name ?? ''
            ) || `Contact ${contact.id}`,
        })
      }
    />
  );
}

export function CreateTaskForm({
  journalId,
  onCreated,
  onCancel,
  onBusyChange,
  autoFocusText = false,
}: CreateTaskFormProps) {
  const fieldIdPrefix = useId();
  const textInputId = `${fieldIdPrefix}-text`;
  const dueJournalInputId = `${fieldIdPrefix}-due-journal`;
  const contactsInputId = `${fieldIdPrefix}-contacts`;

  const focusField = (id: string) => document.getElementById(id)?.focus();

  const form = useForm<CreateTaskFormValues>({
    resolver: zodResolver(createTaskSchema),
    defaultValues: { text: '', dueJournal: null, contacts: [] },
  });
  // `useWatch` rather than `form.watch`: the subscription form is the one the
  // React Compiler can follow, and `watch` makes it skip this component
  // wholesale.
  const chosen = useWatch({ control: form.control, name: 'dueJournal' });

  const create = useCreateTask();
  const busy = create.isPending;

  // An effect event, so a host passing a fresh callback each render is not
  // told "idle" on every one of them.
  const reportIdleOnLeave = useEffectEvent(() => onBusyChange?.(false));
  useEffect(() => () => reportIdleOnLeave(), []);

  // Explicit rather than left to a host's "first tabbable node", which a
  // control added above the text field later would change silently.
  const focusTextOnMount = useEffectEvent(() => {
    if (autoFocusText) focusField(textInputId);
  });
  useEffect(() => focusTextOnMount(), []);

  const onSubmit = (values: CreateTaskFormValues) => {
    if (!values.dueJournal) return;

    onBusyChange?.(true);
    create.mutate(
      {
        journalId,
        text: values.text,
        due_journal_id: Number(values.dueJournal.id),
        // Omitted rather than sent empty — see the module docstring.
        ...(values.contacts.length
          ? { contact_ids: values.contacts.map(contact => Number(contact.id)) }
          : {}),
      },
      {
        onSuccess: () => onCreated(),
        onSettled: () => onBusyChange?.(false),
        onError: error => {
          if (!(error instanceof TaskApiError)) return;

          // Focus follows every field message, and it is not a convenience:
          // `FormMessage` is a plain paragraph rather than a live region, so a
          // message nobody is moved to is a message a screen-reader user never
          // hears. Moving into the described input announces it.
          const reject = (field: keyof CreateTaskFormValues, id: string) => {
            form.setError(field, { type: 'server', message: error.message });
            focusField(id);
          };

          if (error.code === TASK_DUE_JOURNAL_NOT_FUTURE) {
            // Both sides read the user's *configured* zone — the picker through
            // `useUserSettings` — so this is not a browser-versus-server
            // disagreement. It is the window between them: settings still
            // loading when the list was built, a date rolling over mid-form, a
            // clock askew. When they differ the server is right.
            reject('dueJournal', dueJournalInputId);
            return;
          }

          if (error.code === CONTACT_NOT_FOUND) {
            reject('contacts', contactsInputId);
            return;
          }

          const field = FIELD_FOR_VALIDATION_ERROR.get(
            taskValidationField(error) ?? ''
          );
          if (field) {
            reject(field, field === 'text' ? textInputId : dueJournalInputId);
          }
          // A refusal naming a field this form has no input for — or one that
          // is not a validation error at all — has already been reported by
          // the hook's toast, and the form stays with everything the user
          // typed still in it.
        },
      }
    );
  };

  // The text is checked by the schema so its message can name the field; the
  // journal gates the button, because a form that cannot be sent should not
  // look ready to send.
  const canSubmit = chosen != null && !busy;

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className='space-y-4'
        aria-busy={busy}
        noValidate
      >
        <FormField
          control={form.control}
          name='text'
          render={({ field }) => (
            <FormItem>
              <FormLabel htmlFor={textInputId}>What needs doing</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  id={textInputId}
                  autoComplete='off'
                  placeholder='Print the permit before the meeting'
                  disabled={busy}
                  data-testid='create-task-text'
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='dueJournal'
          render={({ field }) => (
            <FormItem>
              <FormLabel htmlFor={dueJournalInputId}>
                Journal this task is due in
              </FormLabel>
              <DueJournalFormField
                inputId={dueJournalInputId}
                value={field.value}
                onSelect={journal => field.onChange(journal)}
                disabled={busy}
              />
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='contacts'
          render={({ field }) => (
            <FormItem>
              <FormLabel htmlFor={contactsInputId}>
                Contacts (optional)
              </FormLabel>
              {field.value.length > 0 && (
                <ul className='flex flex-wrap gap-1'>
                  {field.value.map(contact => (
                    <li key={contact.id}>
                      <Badge variant='secondary' className='text-xs'>
                        {contact.name}
                        <button
                          type='button'
                          className='hover:text-destructive ml-1'
                          aria-label={`Remove ${contact.name}`}
                          disabled={busy}
                          onClick={() =>
                            field.onChange(
                              field.value.filter(
                                chosenContact => chosenContact.id !== contact.id
                              )
                            )
                          }
                        >
                          <X aria-hidden='true' className='h-3 w-3' />
                        </button>
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
              <ContactsField
                inputId={contactsInputId}
                chosen={field.value}
                disabled={busy}
                onChoose={contact => {
                  if (field.value.some(chosen => chosen.id === contact.id)) {
                    return;
                  }
                  field.onChange([...field.value, contact]);
                }}
              />
              <FormDescription>
                Anyone this commitment involves. They are named on the task
                wherever it appears, and can be changed later.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {/* `DialogFooter` is a plain flex row needing no dialog around it.
            The test ids keep their historical `dialog` names. */}
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            onClick={onCancel}
            disabled={busy}
            data-testid='create-task-dialog-cancel'
          >
            Cancel
          </Button>
          <Button
            type='submit'
            disabled={!canSubmit}
            data-testid='create-task-dialog-submit'
          >
            Create task
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
