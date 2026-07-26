/**
 * JournalTagManagementDialog — journal-domain adapter over the shared
 * {@link TagFormDialog} for editing an existing journal tag.
 *
 * Supplies the journal tag hooks and the candidate parent/merge lists; the
 * shared dialog owns the form, validation and the destructive confirmations.
 */

'use client';

import { useMemo } from 'react';
import {
  useJournalTags,
  useUpdateJournalTag,
  useDeleteJournalTag,
  useMergeJournalTag,
} from '@/lib/api/journals';
import {
  TagFormDialog,
  type TagFormOption,
  type TagFormValues,
} from '@/components/shared/TagFormDialog';
import { collectDescendantIds } from '@/lib/tags/tagDescendants';
import { journalTagView } from '@/lib/tags/buildTagTree';
import { JOURNAL_TAG_LIMITS } from './JournalCreateTagDialog';
import type { JournalTag } from '@/types/journals';

export interface JournalTagManagementDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly tag: JournalTag;
}

export function JournalTagManagementDialog({
  open,
  onOpenChange,
  tag,
}: JournalTagManagementDialogProps) {
  const { data: allTagsData } = useJournalTags();
  const { mutateAsync: updateTag, isPending: isUpdating } =
    useUpdateJournalTag();
  const { mutateAsync: deleteTag, isPending: isDeleting } =
    useDeleteJournalTag();
  const { mutateAsync: mergeTag, isPending: isMerging } = useMergeJournalTag();

  // The tag's own subtree is off limits to both dropdowns, for the same reason:
  // re-parenting a tag under its own descendant would make it its own ancestor,
  // and merging it into one would leave the surviving hierarchy running through
  // a tag that no longer exists. The backend rejects both with a 400, so
  // neither is ever offered.
  const candidateTags: TagFormOption[] = useMemo(() => {
    const allTags = allTagsData?.data ?? [];
    const excluded = collectDescendantIds(allTags, tag.id, journalTagView);
    return allTags
      .filter(
        candidate => candidate.id !== tag.id && !excluded.has(candidate.id)
      )
      .map(candidate => ({ id: candidate.id, name: candidate.name }));
  }, [allTagsData?.data, tag.id]);

  const initialValues: TagFormValues = useMemo(
    () => ({
      name: tag.name,
      color: tag.color || '',
      description: tag.description || '',
      parentId: tag.parent_id ?? null,
    }),
    [
      // Keyed on the subject's id too, so a different tag with identical
      // attributes still re-seeds the form rather than inheriting a draft.
      tag.id,
      tag.name,
      tag.color,
      tag.description,
      tag.parent_id,
    ]
  );

  const handleSubmit = async (values: TagFormValues) => {
    // The service records a field as changed whenever the value it receives
    // differs from what is stored, and `'' != None`. The form normalises an
    // absent description to '', so sending it unconditionally would rewrite
    // null to '' just for opening the dialog and saving — a phantom edit that
    // ITER17-005 would turn into a phantom history entry. Send it only when the
    // user actually changed it, which still allows clearing real text.
    const descriptionChanged = values.description !== (tag.description ?? '');

    await updateTag({
      id: tag.id,
      attributes: {
        name: values.name,
        // An empty colour means "this tag has none". The API has no signal for
        // clearing it (an explicit null is rejected, and `JournalTag` treats ''
        // as malformed), so omit it and leave the stored value alone — sending
        // '' would 400 every edit of a colourless tag.
        ...(values.color ? { color: values.color } : {}),
        ...(descriptionChanged ? { description: values.description } : {}),
        parent_id: values.parentId,
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
      limits={JOURNAL_TAG_LIMITS}
      entityNounPlural='journals'
      onDelete={() => deleteTag(tag.id)}
      isDeleting={isDeleting}
      onMerge={targetId => mergeTag({ sourceId: tag.id, targetId })}
      isMerging={isMerging}
      mergeOptions={candidateTags}
    />
  );
}
