/**
 * JournalCreateTagDialog — journal-domain adapter over the shared
 * {@link TagFormDialog} for creating a journal tag.
 *
 * Unlike the contacts create dialog, this one offers a parent picker: journal
 * tags are created from the sidebar, where nesting a new tag under an existing
 * one is the common case.
 */

'use client';

import { useMemo } from 'react';
import { useJournalTags, useCreateJournalTag } from '@/lib/api/journals';
import {
  TagFormDialog,
  type TagFormLimits,
  type TagFormOption,
  type TagFormValues,
} from '@/components/shared/TagFormDialog';

/**
 * Limits enforced by the journal tag API: `name` is capped at 100
 * (`JournalTagCreateAttributes`), `description` is an unbounded TEXT column.
 */
export const JOURNAL_TAG_LIMITS: TagFormLimits = { name: 100 };

export interface JournalCreateTagDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

const EMPTY_TAG: TagFormValues = {
  name: '',
  color: '#000000',
  description: '',
  parentId: null,
};

export function JournalCreateTagDialog({
  open,
  onOpenChange,
}: JournalCreateTagDialogProps) {
  const { data: allTagsData } = useJournalTags();
  const { mutateAsync: createTag, isPending: isCreating } =
    useCreateJournalTag();

  const parentOptions: TagFormOption[] = useMemo(
    () =>
      (allTagsData?.data ?? []).map(tag => ({ id: tag.id, name: tag.name })),
    [allTagsData?.data]
  );

  const initialValues = useMemo(() => EMPTY_TAG, []);

  const handleSubmit = async (values: TagFormValues) => {
    await createTag({
      name: values.name,
      color: values.color || undefined,
      ...(values.description ? { description: values.description } : {}),
      ...(values.parentId ? { parent_id: values.parentId } : {}),
    });
  };

  return (
    <TagFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title='Create Tag'
      description='Add a new tag to organise your journals.'
      submitLabel='Create Tag'
      submittingLabel='Creating...'
      initialValues={initialValues}
      parentOptions={parentOptions}
      onSubmit={handleSubmit}
      isSubmitting={isCreating}
      limits={JOURNAL_TAG_LIMITS}
      entityNounPlural='journals'
    />
  );
}
