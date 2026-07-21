/**
 * ContactTagsEditor — contact-domain adapter over the shared {@link TagsEditor}.
 *
 * Wires the contact tag hooks (assigned tags, all tags, assign/remove/create
 * mutations) into the domain-agnostic editor and maps contact `TagResource`s
 * onto the normalised `TagView` shape.
 */

'use client';

import { useMemo } from 'react';
import { TagsEditor, type TagView } from '@/components/shared/TagsEditor';
import { TAG_COLORS } from '@/lib/constants';
import {
  useContactTags,
  useTags,
  useAssignContactTag,
  useRemoveContactTag,
  useCreateTag,
} from '@/lib/api/contacts';
import type { TagResource } from '@/types/contacts';

interface ContactTagsEditorProps {
  readonly contactId: string;
  readonly className?: string;
}

function toTagView(tag: TagResource): TagView {
  return {
    id: tag.id,
    name: tag.attributes.name,
    color: tag.attributes.color,
    parentId:
      tag.attributes.parent_id != null
        ? String(tag.attributes.parent_id)
        : null,
  };
}

/**
 * Interactive tag editor for the contact detail page.
 * Replaces the static TagsCard with add, remove, and create flows.
 */
export function ContactTagsEditor({
  contactId,
  className,
}: ContactTagsEditorProps) {
  const { data: contactTagsData, isLoading: isLoadingContactTags } =
    useContactTags(contactId);
  const {
    data: allTagsData,
    isLoading: isLoadingAllTags,
    isError: isAllTagsError,
  } = useTags();

  const assignTag = useAssignContactTag();
  const removeTag = useRemoveContactTag();
  const createTag = useCreateTag();

  const assignedTags = useMemo(
    () => (contactTagsData?.data ?? []).map(toTagView),
    [contactTagsData?.data]
  );
  const allTags = useMemo(
    () => (allTagsData?.data ?? []).map(toTagView),
    [allTagsData?.data]
  );

  const handleCreate = async (name: string, color: string) => {
    const response = await createTag.mutateAsync({ name, color });
    try {
      await assignTag.mutateAsync({ contactId, tagId: response.data.id });
    } catch {
      // The tag was created; only the assignment failed (its hook already
      // toasted). Swallow so the editor leaves the create form — retrying there
      // would re-create the same name and fail. The new tag is in the
      // invalidated list, so the user can just select it.
    }
  };

  return (
    <TagsEditor
      assignedTags={assignedTags}
      allTags={allTags}
      isLoading={isLoadingContactTags || isLoadingAllTags}
      isError={isAllTagsError}
      isMutating={
        assignTag.isPending || removeTag.isPending || createTag.isPending
      }
      colors={TAG_COLORS}
      onAssign={tagId => assignTag.mutate({ contactId, tagId })}
      onRemove={tagId => removeTag.mutate({ contactId, tagId })}
      onCreate={handleCreate}
      rootTestId='contact-tags-editor'
      className={className}
    />
  );
}
