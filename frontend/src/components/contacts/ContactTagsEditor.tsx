/**
 * ContactTagsEditor component for managing tags on a contact.
 *
 * Provides an interactive tag editor with:
 * - View assigned tags as dismissible badges
 * - Add existing tags via searchable popover
 * - Create new tags inline with name and colour
 * - Remove tags with X button
 */

'use client';

import { useMemo, useState } from 'react';
import { Tag, X, Plus, Palette } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
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

/**
 * Interactive tag editor for the contact detail page.
 * Replaces the static TagsCard with add, remove, and create flows.
 */
export function ContactTagsEditor({
  contactId,
  className,
}: ContactTagsEditorProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newTagColor, setNewTagColor] = useState<string>(TAG_COLORS[0]);

  const { data: contactTagsData, isLoading: isLoadingContactTags } =
    useContactTags(contactId);
  const {
    data: allTagsData,
    isLoading: isLoadingAllTags,
    isError: isAllTagsError,
  } = useTags();

  // Mutations
  const assignTag = useAssignContactTag();
  const removeTag = useRemoveContactTag();
  const createTag = useCreateTag();

  const assignedTags = useMemo(
    () => contactTagsData?.data ?? [],
    [contactTagsData?.data]
  );
  const allTags = useMemo(() => allTagsData?.data ?? [], [allTagsData?.data]);
  const assignedTagIds = useMemo(
    () => new Set(assignedTags.map(t => t.id)),
    [assignedTags]
  );

  // Filter unassigned tags matching the search query
  const unassignedTags = useMemo(() => {
    const filtered = allTags.filter(tag => !assignedTagIds.has(tag.id));
    if (!searchQuery.trim()) return filtered;
    return filtered.filter(tag =>
      tag.attributes.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [allTags, assignedTagIds, searchQuery]);

  // Check if an exact match exists (for showing "Create" option)
  const exactMatchExists = useMemo(() => {
    if (!searchQuery.trim()) return true;
    return allTags.some(
      tag =>
        tag.attributes.name.toLowerCase() === searchQuery.trim().toLowerCase()
    );
  }, [allTags, searchQuery]);

  const isMutating =
    assignTag.isPending || removeTag.isPending || createTag.isPending;

  const handleAssignTag = (tagId: string) => {
    assignTag.mutate({ contactId, tagId });
    setIsAddOpen(false);
    setSearchQuery('');
  };

  const handleRemoveTag = (tagId: string) => {
    removeTag.mutate({ contactId, tagId });
  };

  const handleCreateAndAssign = async () => {
    const trimmedName = searchQuery.trim();
    if (!trimmedName) return;

    try {
      const response = await createTag.mutateAsync({
        name: trimmedName,
        color: newTagColor,
      });
      const newTagId = response.data.id;
      assignTag.mutate({ contactId, tagId: newTagId });
      setIsAddOpen(false);
      setSearchQuery('');
      setIsCreating(false);
      setNewTagColor(TAG_COLORS[0]);
    } catch {
      // Error handling via toast in the hook
    }
  };

  const handleStartCreate = () => {
    setIsCreating(true);
  };

  const handleCancelCreate = () => {
    setIsCreating(false);
    setNewTagColor(TAG_COLORS[0]);
  };

  // Compute tag display with hierarchy path
  const getTagDisplayName = (tag: TagResource): string => {
    if (!tag.attributes.parent_id) return tag.attributes.name;
    const parent = allTags.find(t => t.id === String(tag.attributes.parent_id));
    if (parent) return `${parent.attributes.name} › ${tag.attributes.name}`;
    return tag.attributes.name;
  };

  if (isLoadingContactTags || isLoadingAllTags) {
    return (
      <div className={className} data-testid='tags-loading'>
        <div className='flex flex-wrap gap-2'>
          <Skeleton className='h-6 w-16 rounded-full' />
          <Skeleton className='h-6 w-20 rounded-full' />
          <Skeleton className='h-6 w-24 rounded-full' />
          <Skeleton className='h-6 w-16 rounded-full' />
        </div>
      </div>
    );
  }

  if (isAllTagsError) {
    return (
      <div className={className} data-testid='tags-error'>
        <p className='text-destructive text-sm'>
          Failed to load tag definitions.
        </p>
      </div>
    );
  }

  return (
    <div className={className} data-testid='contact-tags-editor'>
      <div className='flex flex-wrap items-center gap-2'>
        {/* Assigned tag badges */}
        {assignedTags.map(tag => (
          <Badge
            key={tag.id}
            variant='secondary'
            className='gap-1 pr-1'
            data-testid={`tag-badge-${tag.id}`}
            style={
              tag.attributes.color
                ? {
                    borderColor: tag.attributes.color,
                    borderWidth: '1px',
                  }
                : undefined
            }
          >
            <Tag className='h-3 w-3' aria-hidden='true' />
            <span>{tag.attributes.name}</span>
            <button
              type='button'
              onClick={() => handleRemoveTag(tag.id)}
              disabled={isMutating}
              className='hover:bg-muted ml-0.5 rounded-sm p-0.5 transition-colors'
              aria-label={`Remove tag ${tag.attributes.name}`}
              data-testid={`remove-tag-${tag.id}`}
            >
              <X className='h-3 w-3' />
            </button>
          </Badge>
        ))}

        {/* Empty state */}
        {assignedTags.length === 0 && (
          <span className='text-muted-foreground text-sm'>
            No tags assigned
          </span>
        )}

        {/* Add Tag button */}
        <Popover
          open={isAddOpen}
          onOpenChange={open => {
            setIsAddOpen(open);
            if (!open) {
              setSearchQuery('');
              setIsCreating(false);
              setNewTagColor(TAG_COLORS[0]);
            }
          }}
        >
          <PopoverTrigger asChild>
            <Button
              variant='outline'
              size='sm'
              className='h-6 gap-1 text-xs'
              disabled={isMutating}
              data-testid='add-tag-button'
            >
              <Plus className='h-3 w-3' />
              Add Tag
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-72 p-3' align='start'>
            {!isCreating ? (
              <div className='space-y-2'>
                {/* Search Input */}
                <Input
                  placeholder='Search or create a tag...'
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className='h-8 text-sm'
                  data-testid='tag-search-input'
                  autoFocus
                />

                {/* Tag list */}
                <div className='max-h-48 overflow-y-auto'>
                  {unassignedTags.map(tag => (
                    <button
                      key={tag.id}
                      type='button'
                      onClick={() => handleAssignTag(tag.id)}
                      className='hover:bg-accent flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors'
                      data-testid={`tag-option-${tag.id}`}
                      disabled={isMutating}
                    >
                      {tag.attributes.color && (
                        <span
                          className='h-3 w-3 shrink-0 rounded-full'
                          style={{
                            backgroundColor: tag.attributes.color,
                          }}
                        />
                      )}
                      <span>{getTagDisplayName(tag)}</span>
                    </button>
                  ))}

                  {/* Create option */}
                  {searchQuery.trim() && !exactMatchExists && (
                    <button
                      type='button'
                      onClick={handleStartCreate}
                      className='hover:bg-accent flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors'
                      data-testid='create-tag-option'
                      disabled={isMutating}
                    >
                      <Plus className='text-muted-foreground h-3 w-3' />
                      <span>Create &ldquo;{searchQuery.trim()}&rdquo;</span>
                    </button>
                  )}

                  {/* No results */}
                  {unassignedTags.length === 0 &&
                    (exactMatchExists || !searchQuery.trim()) && (
                      <p className='text-muted-foreground py-2 text-center text-sm'>
                        No tags available
                      </p>
                    )}
                </div>
              </div>
            ) : (
              /* Create tag mini-form */
              <div className='space-y-3'>
                <div className='space-y-1'>
                  <label htmlFor='new-tag-name' className='text-sm font-medium'>
                    Tag Name
                  </label>
                  <Input
                    id='new-tag-name'
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    className='h-8 text-sm'
                    data-testid='new-tag-name-input'
                    autoFocus
                  />
                </div>

                <div className='space-y-1'>
                  <label className='flex items-center gap-1 text-sm font-medium'>
                    <Palette className='h-3 w-3' />
                    Colour
                  </label>
                  <div
                    className='flex flex-wrap gap-1.5'
                    data-testid='colour-picker'
                  >
                    {TAG_COLORS.map(color => (
                      <button
                        key={color}
                        type='button'
                        onClick={() => setNewTagColor(color)}
                        className={cn(
                          'h-6 w-6 rounded-full border-2 transition-transform',
                          newTagColor === color
                            ? 'border-foreground scale-110'
                            : 'border-transparent hover:scale-105'
                        )}
                        style={{ backgroundColor: color }}
                        aria-label={`Select colour ${color}`}
                        data-testid={`colour-${color}`}
                      />
                    ))}
                  </div>
                </div>

                <div className='flex gap-2'>
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={handleCancelCreate}
                    className='flex-1'
                    data-testid='cancel-create-tag'
                  >
                    Cancel
                  </Button>
                  <Button
                    size='sm'
                    onClick={handleCreateAndAssign}
                    disabled={!searchQuery.trim() || isMutating}
                    className='flex-1'
                    data-testid='confirm-create-tag'
                  >
                    Create & Add
                  </Button>
                </div>
              </div>
            )}
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
}
