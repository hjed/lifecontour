/**
 * TagManagementDialog — contact-domain adapter over the shared
 * {@link TagFormDialog}.
 *
 * Supplies the contact tag hooks and the candidate parent/merge lists; the
 * shared dialog owns the form, validation and the destructive confirmations.
 */

'use client';

import { useMemo } from 'react';
import { TagResource } from '@/types/contacts';
import {
  useUpdateTag,
  useDeleteTag,
  useTags,
  useMergeTag,
} from '@/lib/api/contacts';
import {
  TagFormDialog,
  type TagFormOption,
  type TagFormValues,
} from '@/components/shared/TagFormDialog';
import { CONTACT_TAG_LIMITS } from './CreateTagDialog';

export interface TagManagementDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly tag: TagResource;
}

export function TagManagementDialog({
  open,
  onOpenChange,
  tag,
}: TagManagementDialogProps) {
  const { mutateAsync: updateTag, isPending: isUpdating } = useUpdateTag();
  const { mutateAsync: deleteTag, isPending: isDeleting } = useDeleteTag();
  const { mutateAsync: mergeTag, isPending: isMerging } = useMergeTag();
  const { data: allTagsData } = useTags();

  // Prevent self-parenting and self-merging. Deeper cycles are rejected by the
  // backend rather than filtered here.
  const candidateTags: TagFormOption[] = useMemo(
    () =>
      (allTagsData?.data ?? [])
        .filter(t => t.id !== tag.id)
        .map(t => ({ id: t.id, name: t.attributes.name })),
    [allTagsData?.data, tag.id]
  );

  const initialValues: TagFormValues = useMemo(
    () => ({
      name: tag.attributes.name,
      color: tag.attributes.color || '',
      description: tag.attributes.description || '',
      parentId: tag.attributes.parent_id
        ? String(tag.attributes.parent_id)
        : null,
    }),
    [
      tag.attributes.name,
      tag.attributes.color,
      tag.attributes.description,
      tag.attributes.parent_id,
    ]
  );

  const handleSubmit = async (values: TagFormValues) => {
    await updateTag({
      id: tag.id,
      attributes: {
        name: values.name,
        color: values.color,
        description: values.description,
        parent_id:
          values.parentId === null
            ? null
            : Number.parseInt(values.parentId, 10),
      },
    });
  };

  return (
    <TagFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title='Edit Tag'
      description="Make changes to your tag here. Click save when you're done."
      submitLabel='Save Changes'
      submittingLabel='Saving...'
      initialValues={initialValues}
      parentOptions={candidateTags}
      onSubmit={handleSubmit}
      isSubmitting={isUpdating}
      limits={CONTACT_TAG_LIMITS}
      entityNounPlural='contacts'
      onDelete={() => deleteTag(tag.id)}
      isDeleting={isDeleting}
      onMerge={targetId => mergeTag({ sourceId: tag.id, targetId })}
      isMerging={isMerging}
      mergeOptions={candidateTags}
    />
  );
}
