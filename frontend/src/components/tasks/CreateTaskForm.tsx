/**
 * Creates a task in the journal it arose in.
 *
 * The form on its own, so any host can mount it: `CreateTaskDialog` on the
 * journal page and the New dialog's Task panel. A host says where the
 * creating journal comes from and hears back through `onCreated`, `onCancel`
 * and `onBusyChange`.
 *
 * The specification's *Creating a task* is four sentences and every one of
 * them is a rule this form keeps:
 *
 * - **The creating journal is the journal being viewed.** On the journal page
 *   it "is never chosen separately", so the host fixes it (`kind: 'fixed'`)
 *   and there is no field for it. The New dialog has no journal around it, and
 *   the navigation specification has it *ask* — pre-filled with the journal
 *   being viewed, "otherwise the user must choose" — so there the host asks
 *   for a field (`kind: 'choose'`). Either way it travels in the path of
 *   `POST /api/journals/{id}/tasks`, never in the body.
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
import {
  CreatingJournalField,
  type ChosenJournal,
} from '@/components/tasks/CreatingJournalField';
import { DueJournalFormField } from '@/components/journals/FutureJournalPicker';
import {
  CONTACT_NOT_FOUND,
  TASK_DUE_JOURNAL_NOT_FUTURE,
  TaskApiError,
  taskAnchorField,
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

/** A chosen creating journal, as `CreatingJournalField` yields it. */
const creatingJournalSchema = z.object({
  id: z.string(),
  title: z.string(),
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
  /**
   * Always present in the values. In `fixed` mode it holds the host's journal
   * from the start and has no input, so the rule below can only fail where
   * the user is the one choosing.
   */
  creatingJournal: creatingJournalSchema
    .nullable()
    .superRefine((journal, ctx) => {
      if (journal === null) {
        ctx.addIssue({
          code: 'custom',
          message: 'Choose the journal this task arose in.',
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

/**
 * Where the task's **creating** journal comes from.
 *
 * - `fixed`: the journal page — the journal being viewed, never offered as a
 *   choice. A refusal of it has no field to land on and is left to the toast.
 * - `choose`: the New dialog — a required search, starting from `initial`
 *   (the journal being viewed, when there is one).
 */
export type CreatingJournalSource =
  | { readonly kind: 'fixed'; readonly id: string }
  | { readonly kind: 'choose'; readonly initial?: ChosenJournal };

export interface CreateTaskFormProps {
  /** Where the creating journal comes from; see `CreatingJournalSource`. */
  readonly creatingJournal: CreatingJournalSource;
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

/** The creating journal a source starts the form with. */
function initialCreatingJournal(
  source: CreatingJournalSource
): ChosenJournal | null {
  if (source.kind === 'fixed') return { id: source.id, title: '' };
  return source.initial ?? null;
}

export function CreateTaskForm({
  creatingJournal,
  onCreated,
  onCancel,
  onBusyChange,
  autoFocusText = false,
}: CreateTaskFormProps) {
  const fieldIdPrefix = useId();
  const textInputId = `${fieldIdPrefix}-text`;
  const creatingJournalInputId = `${fieldIdPrefix}-creating-journal`;
  const choosesCreatingJournal = creatingJournal.kind === 'choose';
  const dueJournalInputId = `${fieldIdPrefix}-due-journal`;
  const contactsInputId = `${fieldIdPrefix}-contacts`;

  const focusField = (id: string) => document.getElementById(id)?.focus();

  const form = useForm<CreateTaskFormValues>({
    resolver: zodResolver(createTaskSchema),
    defaultValues: {
      text: '',
      creatingJournal: initialCreatingJournal(creatingJournal),
      dueJournal: null,
      contacts: [],
    },
  });

  // A `choose` host may learn the journal being viewed after the form mounted
  // (its read still in flight). It is applied then — but only to a field the
  // user has not touched, so a slow read never overwrites their choice, nor
  // what they have typed towards one.
  const lateInitial =
    creatingJournal.kind === 'choose' ? creatingJournal.initial : undefined;
  const applyLateInitial = useEffectEvent((journal: ChosenJournal) => {
    if (form.getFieldState('creatingJournal').isTouched) return;
    if (form.getValues('creatingJournal')?.id === journal.id) return;
    form.setValue('creatingJournal', journal);
  });
  useEffect(() => {
    if (lateInitial) applyLateInitial(lateInitial);
  }, [lateInitial]);
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
    if (!values.dueJournal || !values.creatingJournal) return;

    onBusyChange?.(true);
    create.mutate(
      {
        journalId: values.creatingJournal.id,
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

          // An unreachable journal names its anchor. The creating journal has
          // a field only when the user chose it; a fixed one is the page's
          // own journal, and its refusal stays with the toast.
          const anchor = taskAnchorField(error);
          if (anchor === 'due') {
            reject('dueJournal', dueJournalInputId);
            return;
          }
          if (anchor === 'creating') {
            if (choosesCreatingJournal) {
              reject('creatingJournal', creatingJournalInputId);
            }
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

  // The text and a chosen creating journal are checked by the schema, so their
  // messages can name the field. The due journal gates the button, because a
  // form that cannot be sent should not look ready to send. The creating
  // journal does not: when it is pre-filled the user never touches it, and when
  // it is not, the message on submit says what is missing where it is missing.
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

        {choosesCreatingJournal && (
          <FormField
            control={form.control}
            name='creatingJournal'
            render={({ field }) => (
              <FormItem>
                <FormLabel htmlFor={creatingJournalInputId}>
                  Journal this task arose in
                </FormLabel>
                <CreatingJournalField
                  inputId={creatingJournalInputId}
                  value={field.value}
                  onChange={journal => {
                    field.onChange(journal);
                    // Every edit marks the field touched, which is what keeps
                    // a late pre-fill off it.
                    field.onBlur();
                  }}
                  disabled={busy}
                />
                <FormDescription>
                  Where the commitment was made. Any of your journals.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

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
            // A full touch target on phones, where the New sheet shows it.
            className='min-h-11 md:min-h-9'
            data-testid='create-task-dialog-cancel'
          >
            Cancel
          </Button>
          <Button
            type='submit'
            disabled={!canSubmit}
            className='min-h-11 md:min-h-9'
            data-testid='create-task-dialog-submit'
          >
            Create task
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
