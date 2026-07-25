/**
 * CreateTagDialog — contact-domain adapter over the shared {@link TagFormDialog}.
 *
 * Contacts create tags from the sidebar at the root of the hierarchy (or under
 * an explicit `parentId` supplied by the caller), so no parent field is offered.
 */

'use client';

import { useMemo } from 'react';
import { useCreateTag } from '@/lib/api/contacts';
import {
  TagFormDialog,
  type TagFormLimits,
  type TagFormValues,
} from '@/components/shared/TagFormDialog';

/** Limits enforced by the contact tag API. */
export const CONTACT_TAG_LIMITS: TagFormLimits = { name: 50, description: 255 };

export interface CreateTagDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly parentId?: number; // Optional parent tag
}

const EMPTY_TAG: TagFormValues = {
  name: '',
  color: '#000000',
  description: '',
  parentId: null,
};

export function CreateTagDialog({
  open,
  onOpenChange,
  parentId,
}: CreateTagDialogProps) {
  const { mutateAsync: createTag, isPending: isCreating } = useCreateTag();

  const initialValues = useMemo(() => EMPTY_TAG, []);

  const handleSubmit = async (values: TagFormValues) => {
    await createTag({
      name: values.name,
      color: values.color || undefined,
      description: values.description || undefined,
      parent_id: parentId,
    });
  };

  return (
    <TagFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title='Create Tag'
      description='Add a new tag to organize your contacts.'
      submitLabel='Create Tag'
      submittingLabel='Creating...'
      initialValues={initialValues}
      onSubmit={handleSubmit}
      isSubmitting={isCreating}
      limits={CONTACT_TAG_LIMITS}
      entityNounPlural='contacts'
    />
  );
}
