/**
 * TagFormDialog — domain-agnostic create/edit dialog for a tag.
 *
 * Both tag namespaces (contacts, journals) manage tags with the same fields —
 * name, colour, description and an optional parent — and the same destructive
 * operations. This component owns that form and its validation; the domain
 * adapters own the data hooks and decide which capabilities to offer by which
 * callbacks they pass:
 *
 * - `parentOptions` omitted  → no parent field
 * - `onDelete` omitted       → no delete affordance
 * - `onMerge` omitted        → no merge section
 *
 * `initialValues` must be referentially stable (memoise it in the adapter): the
 * form resets to it whenever it changes or the dialog opens.
 */

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';

/**
 * The parent select's own value space, kept disjoint from tag ids.
 *
 * Radix Select cannot hold an empty-string value, so "no parent" needs a
 * sentinel — but a bare sentinel like `'none'` could collide with a real id in a
 * namespace whose ids are arbitrary strings, silently making that tag
 * unselectable as a parent. Prefixing every real id keeps the two disjoint
 * whatever the id looks like.
 */
const ROOT_PARENT_VALUE = 'root';
const PARENT_VALUE_PREFIX = 'tag:';

function toParentValue(parentId: string | null): string {
  return parentId === null
    ? ROOT_PARENT_VALUE
    : `${PARENT_VALUE_PREFIX}${parentId}`;
}

function fromParentValue(value: string): string | null {
  return value === ROOT_PARENT_VALUE
    ? null
    : value.slice(PARENT_VALUE_PREFIX.length);
}

/** Both tag backends store a 7-character `#RRGGBB` colour. */
const HEX_COLOUR_PATTERN = /^#[0-9a-fA-F]{6}$/;

/**
 * Field length limits, which each namespace takes from its own API. A client
 * limit stricter than the API's would make a tag created through the API or MCP
 * uneditable here — the form validates on every submit, so an over-length name
 * inherited from elsewhere would block a colour change too.
 */
export interface TagFormLimits {
  /** Omit for no limit. */
  readonly name?: number | undefined;
  /** Omit for no limit. */
  readonly description?: number | undefined;
}

interface InternalFormValues {
  name: string;
  color: string;
  description: string;
  parentId: string;
}

function buildFormSchema(limits: TagFormLimits) {
  const name = z.string().min(1, 'Name is required');
  const description = z.string();

  return z.object({
    name:
      limits.name === undefined
        ? name
        : name.max(
            limits.name,
            `Name must be no more than ${limits.name} characters`
          ),
    color: z
      .string()
      .refine(value => value === '' || HEX_COLOUR_PATTERN.test(value), {
        message: 'Must be a hex colour, for example #38A169',
      }),
    description:
      limits.description === undefined
        ? description
        : description.max(
            limits.description,
            `Description must be no more than ${limits.description} characters`
          ),
    parentId: z.string(),
  });
}

/** A tag reduced to what the dialog's dropdowns need. */
export interface TagFormOption {
  readonly id: string;
  readonly name: string;
}

/** The values the dialog hands back, with the root parent normalised to null. */
export interface TagFormValues {
  readonly name: string;
  readonly color: string;
  readonly description: string;
  readonly parentId: string | null;
}

export interface TagFormDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly title: string;
  readonly description: string;
  readonly submitLabel: string;
  readonly submittingLabel: string;
  readonly initialValues: TagFormValues;
  /** Candidate parents. Omit to hide the parent field entirely. */
  readonly parentOptions?: readonly TagFormOption[] | undefined;
  readonly onSubmit: (values: TagFormValues) => Promise<void>;
  readonly isSubmitting: boolean;
  /** Field limits from the namespace's API. Defaults to no limit. */
  readonly limits?: TagFormLimits | undefined;
  /** Entity the tag is attached to, e.g. "journals" — destructive copy only. */
  readonly entityNounPlural: string;
  /** Omit to hide the delete affordance. */
  readonly onDelete?: (() => Promise<void>) | undefined;
  readonly isDeleting?: boolean | undefined;
  /** Omit to hide the merge section. */
  readonly onMerge?: ((targetId: string) => Promise<void>) | undefined;
  readonly isMerging?: boolean | undefined;
  readonly mergeOptions?: readonly TagFormOption[] | undefined;
}

function toInternalValues(values: TagFormValues): InternalFormValues {
  return {
    name: values.name,
    color: values.color,
    description: values.description,
    parentId: toParentValue(values.parentId ?? null),
  };
}

export function TagFormDialog({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  submittingLabel,
  initialValues,
  parentOptions,
  onSubmit,
  isSubmitting,
  limits,
  entityNounPlural,
  onDelete,
  isDeleting = false,
  onMerge,
  isMerging = false,
  mergeOptions,
}: TagFormDialogProps) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showMergeConfirm, setShowMergeConfirm] = useState(false);
  const [mergeTargetId, setMergeTargetId] = useState('');

  const nameLimit = limits?.name;
  const descriptionLimit = limits?.description;
  const formSchema = useMemo(
    () => buildFormSchema({ name: nameLimit, description: descriptionLimit }),
    [nameLimit, descriptionLimit]
  );

  const form = useForm<InternalFormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: toInternalValues(initialValues),
  });

  /**
   * Clears the state that lives outside the form.
   *
   * A stale `mergeTargetId` is the dangerous one: it leaves the Merge button
   * enabled on the next open, pointing at a target the user chose in an earlier
   * session of the dialog.
   */
  const resetTransientState = useCallback(() => {
    setMergeTargetId('');
    setShowMergeConfirm(false);
    setShowDeleteConfirm(false);
  }, []);

  /** The single close path, so no caller can skip the reset. */
  const closeDialog = useCallback(() => {
    resetTransientState();
    onOpenChange(false);
  }, [resetTransientState, onOpenChange]);

  // Re-seed the form when the dialog opens or the subject tag changes, so a
  // dialog kept mounted between openings never shows a stale draft. The
  // non-form state is not reset here — every close routes through
  // `closeDialog`, and resetting it in an effect would mean calling setState
  // synchronously during one.
  useEffect(() => {
    if (open) {
      form.reset(toInternalValues(initialValues));
    }
  }, [open, initialValues, form]);

  const handleSubmit = async (values: InternalFormValues) => {
    try {
      await onSubmit({
        name: values.name,
        color: values.color,
        description: values.description,
        parentId: fromParentValue(values.parentId),
      });
      closeDialog();
    } catch {
      // Errors surface as toasts from the adapter's mutation; keep the dialog
      // open so the user can correct the input and retry.
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    try {
      await onDelete();
      closeDialog();
    } catch {
      // Handled by the mutation's error toast.
    }
  };

  const handleMerge = async () => {
    if (!onMerge || !mergeTargetId) return;
    try {
      await onMerge(mergeTargetId);
      closeDialog();
    } catch {
      // Handled by the mutation's error toast.
    }
  };

  const busy = isSubmitting || isDeleting || isMerging;

  return (
    <Dialog
      open={open}
      onOpenChange={newOpen => (newOpen ? onOpenChange(true) : closeDialog())}
    >
      <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-[425px]'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(handleSubmit)}
            className='space-y-4'
          >
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder='Tag name' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {parentOptions && (
              <FormField
                control={form.control}
                name='parentId'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Parent Tag</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder='Select a parent tag' />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value={ROOT_PARENT_VALUE}>
                          None (Root Level)
                        </SelectItem>
                        {parentOptions.map(option => (
                          <SelectItem
                            key={option.id}
                            value={toParentValue(option.id)}
                          >
                            {option.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name='color'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Color</FormLabel>
                  <div className='flex items-center gap-2'>
                    <Input
                      type='color'
                      className='h-10 w-12 p-1'
                      value={
                        HEX_COLOUR_PATTERN.test(field.value)
                          ? field.value
                          : '#000000'
                      }
                      onChange={e => field.onChange(e.target.value)}
                      aria-label='Color Picker'
                    />
                    <FormControl>
                      <Input placeholder='#000000' {...field} />
                    </FormControl>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea placeholder='Optional description' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* With a delete button the footer splits destructive-left /
                confirm-right; without one, Cancel and submit stay grouped. */}
            <DialogFooter
              className={cn('pt-4', onDelete && 'flex-row sm:justify-between')}
            >
              {onDelete ? (
                <AlertDialog
                  open={showDeleteConfirm}
                  onOpenChange={setShowDeleteConfirm}
                >
                  <AlertDialogTrigger asChild>
                    <Button type='button' variant='destructive' disabled={busy}>
                      {isDeleting ? 'Deleting...' : 'Delete Tag'}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        Are you absolutely sure?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        This action cannot be undone. This will permanently
                        delete the tag &quot;{initialValues.name}&quot; and
                        remove it from all {entityNounPlural} it is assigned to.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={handleDelete}
                        disabled={isDeleting}
                        className='bg-destructive hover:bg-destructive/90 text-white'
                      >
                        {isDeleting ? 'Deleting...' : 'Delete'}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              ) : (
                <Button type='button' variant='outline' onClick={closeDialog}>
                  Cancel
                </Button>
              )}

              <Button type='submit' disabled={busy}>
                {isSubmitting ? submittingLabel : submitLabel}
              </Button>
            </DialogFooter>
          </form>
        </Form>

        {onMerge && (
          <>
            <Separator className='my-4' />

            <div className='space-y-4'>
              <div>
                <h4 className='text-sm font-medium'>Merge Tag</h4>
                <p className='text-muted-foreground mt-1 text-sm'>
                  Merge this tag into another one. All {entityNounPlural} and
                  child tags will be moved to the target tag, and this tag will
                  be deleted.
                </p>
              </div>

              <div className='flex gap-2'>
                <Select onValueChange={setMergeTargetId} value={mergeTargetId}>
                  <SelectTrigger className='flex-1' aria-label='Merge into'>
                    <SelectValue placeholder='Select target tag to merge into' />
                  </SelectTrigger>
                  <SelectContent>
                    {(mergeOptions ?? []).map(option => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <AlertDialog
                  open={showMergeConfirm}
                  onOpenChange={setShowMergeConfirm}
                >
                  <AlertDialogTrigger asChild>
                    <Button
                      type='button'
                      variant='secondary'
                      disabled={!mergeTargetId || busy}
                    >
                      {isMerging ? 'Merging...' : 'Merge'}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Confirm Merge</AlertDialogTitle>
                      <AlertDialogDescription>
                        Are you sure you want to merge &quot;
                        {initialValues.name}&quot; into the selected tag? This
                        action cannot be undone. All {entityNounPlural} will be
                        reassigned and this tag will be deleted.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={handleMerge}
                        disabled={isMerging}
                      >
                        {isMerging ? 'Merging...' : 'Confirm Merge'}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
