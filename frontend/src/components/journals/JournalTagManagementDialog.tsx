/**
 * JournalTagManagementDialog — journal-domain adapter over the shared
 * {@link TagFormDialog} for editing an existing journal tag.
 *
 * Delete and merge are deliberately not wired up yet; the shared dialog hides
 * both sections when their callbacks are absent.
 */

'use client';

import { useMemo } from 'react';
import { useJournalTags, useUpdateJournalTag } from '@/lib/api/journals';
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

  // A tag cannot be re-parented under itself or anything below it — the backend
  // rejects the cycle with a 400, so it is never offered as an option.
  const parentOptions: TagFormOption[] = useMemo(() => {
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
    [tag.name, tag.color, tag.description, tag.parent_id]
  );

  const handleSubmit = async (values: TagFormValues) => {
    await updateTag({
      id: tag.id,
      attributes: {
        name: values.name,
        // An empty colour means "this tag has none". The API has no signal for
        // clearing it (an explicit null is rejected, and `JournalTag` treats ''
        // as malformed), so omit it and leave the stored value alone — sending
        // '' would 400 every edit of a colourless tag.
        ...(values.color ? { color: values.color } : {}),
        description: values.description,
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
      parentOptions={parentOptions}
      onSubmit={handleSubmit}
      isSubmitting={isUpdating}
      limits={JOURNAL_TAG_LIMITS}
      entityNounPlural='journals'
    />
  );
}
