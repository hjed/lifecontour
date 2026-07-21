/**
 * JournalTagsEditor — journal-domain adapter over the shared {@link TagsEditor}.
 *
 * Wires the journal tag hooks (all tags, add/remove/create mutations) into the
 * domain-agnostic editor and maps flat `JournalTag`s onto the normalised
 * `TagView` shape. Assigned tags are passed in (they are embedded on the journal
 * detail resource — there is no per-journal assigned-tags endpoint).
 */

'use client';

import { useMemo } from 'react';
import { TagsEditor, type TagView } from '@/components/shared/TagsEditor';
import { TAG_COLORS } from '@/lib/constants';
import {
  useJournalTags,
  useAddJournalTag,
  useRemoveJournalTag,
  useCreateJournalTag,
} from '@/lib/api/journals';
import type { JournalTag } from '@/types/journals';

interface JournalTagsEditorProps {
  readonly journalId: string;
  readonly assignedTags: JournalTag[];
  readonly className?: string;
}

function toTagView(tag: JournalTag): TagView {
  return {
    id: tag.id,
    name: tag.name,
    color: tag.color,
    parentId: tag.parent_id ?? null,
  };
}

/**
 * Interactive tag editor for the journal detail page: searchable add popover,
 * inline create-new-tag with colour, and dismissible colour-coded badges.
 */
export function JournalTagsEditor({
  journalId,
  assignedTags,
  className,
}: JournalTagsEditorProps) {
  const {
    data: allTagsData,
    isLoading: isLoadingAllTags,
    isError: isAllTagsError,
  } = useJournalTags();

  const addTag = useAddJournalTag();
  const removeTag = useRemoveJournalTag();
  const createTag = useCreateJournalTag();

  const assignedTagViews = useMemo(
    () => assignedTags.map(toTagView),
    [assignedTags]
  );
  const allTagViews = useMemo(
    () => (allTagsData?.data ?? []).map(toTagView),
    [allTagsData?.data]
  );

  const handleCreate = async (name: string, color: string) => {
    const response = await createTag.mutateAsync({ name, color });
    try {
      await addTag.mutateAsync({ journalId, tagId: response.data.id });
    } catch {
      // The tag was created; only the assignment failed (its hook already
      // toasted). Swallow so the editor leaves the create form — retrying there
      // would re-create the same name and fail. The new tag is in the
      // invalidated list, so the user can just select it.
    }
  };

  return (
    <TagsEditor
      assignedTags={assignedTagViews}
      allTags={allTagViews}
      isLoading={isLoadingAllTags}
      isError={isAllTagsError}
      isMutating={
        addTag.isPending || removeTag.isPending || createTag.isPending
      }
      colors={TAG_COLORS}
      onAssign={tagId => addTag.mutate({ journalId, tagId })}
      onRemove={tagId => removeTag.mutate({ journalId, tagId })}
      onCreate={handleCreate}
      rootTestId='journal-tags-editor'
      className={className}
    />
  );
}
