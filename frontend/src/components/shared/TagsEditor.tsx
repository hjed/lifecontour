/**
 * TagsEditor — a domain-agnostic inline tag editor.
 *
 * Presentational/controlled component shared by the contact and journal tag
 * editors. It owns all interaction state (popover open, search query, create
 * mode, chosen colour) and renders:
 * - assigned tags as dismissible colour-coded badges
 * - a searchable add popover listing unassigned tags (autocomplete)
 * - an inline create-new-tag form with a colour picker
 *
 * It knows nothing about React Query, fetching, or a specific tag namespace:
 * callers normalise their tags into `TagView` and pass mutation callbacks.
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

// Safe default when a caller passes an empty palette, so the inline create flow
// never seeds `newTagColor` with `undefined`. Current callers always pass a
// non-empty `TAG_COLORS`, so this is defence for the shared contract.
const FALLBACK_TAG_COLOR = '#718096';

/**
 * Normalised, domain-agnostic view of a tag. Adapters map their own tag
 * resources (contact `TagResource`, journal `JournalTag`, …) onto this shape.
 */
export interface TagView {
  readonly id: string;
  readonly name: string;
  readonly color?: string | null;
  readonly parentId?: string | null;
}

interface TagsEditorProps {
  /** Tags currently assigned to the entity, rendered as badges. */
  readonly assignedTags: TagView[];
  /** All tags in the namespace, used for the add list and parent resolution. */
  readonly allTags: TagView[];
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly isMutating: boolean;
  /** Colour palette offered by the inline create form. */
  readonly colors: readonly string[];
  readonly onAssign: (tagId: string) => void;
  readonly onRemove: (tagId: string) => void;
  /** Create a new tag and assign it. Rejects to keep the popover open. */
  readonly onCreate: (name: string, color: string) => Promise<void>;
  /** Root data-testid so each domain keeps a distinct hook. */
  readonly rootTestId?: string;
  readonly className?: string;
}

export function TagsEditor({
  assignedTags,
  allTags,
  isLoading,
  isError,
  isMutating,
  colors,
  onAssign,
  onRemove,
  onCreate,
  rootTestId = 'tags-editor',
  className,
}: TagsEditorProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newTagColor, setNewTagColor] = useState<string>(
    colors[0] ?? FALLBACK_TAG_COLOR
  );

  const assignedTagIds = useMemo(
    () => new Set(assignedTags.map(t => t.id)),
    [assignedTags]
  );

  // Filter unassigned tags matching the search query. Trim before matching so
  // the list and the "Create" affordance (which also trims) stay consistent —
  // a trailing space must not empty the list and hide the create option.
  const unassignedTags = useMemo(() => {
    const filtered = allTags.filter(tag => !assignedTagIds.has(tag.id));
    const query = searchQuery.trim().toLowerCase();
    if (!query) return filtered;
    return filtered.filter(tag => tag.name.toLowerCase().includes(query));
  }, [allTags, assignedTagIds, searchQuery]);

  // Check if an exact match exists (for showing the "Create" option)
  const exactMatchExists = useMemo(() => {
    if (!searchQuery.trim()) return true;
    return allTags.some(
      tag => tag.name.toLowerCase() === searchQuery.trim().toLowerCase()
    );
  }, [allTags, searchQuery]);

  const resetAddState = () => {
    setSearchQuery('');
    setIsCreating(false);
    setNewTagColor(colors[0] ?? FALLBACK_TAG_COLOR);
  };

  const handleAssignTag = (tagId: string) => {
    onAssign(tagId);
    setIsAddOpen(false);
    setSearchQuery('');
  };

  const handleCreateAndAssign = async () => {
    const trimmedName = searchQuery.trim();
    if (!trimmedName) return;

    try {
      // Await so the caller's cache is invalidated (and the new badge rendered)
      // before we close the popover. Fire-and-forget let the editor settle into
      // a "no tags" state when the request resolved late — a flaky missing badge.
      await onCreate(trimmedName, newTagColor);
      setIsAddOpen(false);
      resetAddState();
    } catch {
      // Error surfaced by the caller (toast); keep the popover open.
    }
  };

  const handleStartCreate = () => {
    setIsCreating(true);
  };

  const handleCancelCreate = () => {
    setIsCreating(false);
    setNewTagColor(colors[0] ?? FALLBACK_TAG_COLOR);
  };

  // Compute tag display with hierarchy path
  const getTagDisplayName = (tag: TagView): string => {
    if (!tag.parentId) return tag.name;
    const parent = allTags.find(t => t.id === tag.parentId);
    if (parent) return `${parent.name} › ${tag.name}`;
    return tag.name;
  };

  if (isLoading) {
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

  if (isError) {
    return (
      <div className={className} data-testid='tags-error'>
        <p className='text-destructive text-sm'>
          Failed to load tag definitions.
        </p>
      </div>
    );
  }

  return (
    <div className={className} data-testid={rootTestId}>
      <div className='flex flex-wrap items-center gap-2'>
        {/* Assigned tag badges */}
        {assignedTags.map(tag => (
          <Badge
            key={tag.id}
            variant='secondary'
            className='gap-1 pr-1'
            data-testid={`tag-badge-${tag.id}`}
            style={
              tag.color
                ? {
                    borderColor: tag.color,
                    borderWidth: '1px',
                  }
                : undefined
            }
          >
            <Tag className='h-3 w-3' aria-hidden='true' />
            <span>{tag.name}</span>
            <button
              type='button'
              onClick={() => onRemove(tag.id)}
              disabled={isMutating}
              className='hover:bg-muted ml-0.5 rounded-sm p-0.5 transition-colors'
              aria-label={`Remove tag ${tag.name}`}
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
            if (!open) resetAddState();
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
                  aria-label='Search or create a tag'
                  data-testid='tag-search-input'
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
                      {tag.color && (
                        <span
                          className='h-3 w-3 shrink-0 rounded-full'
                          style={{
                            backgroundColor: tag.color,
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
                  />
                </div>

                <div className='space-y-1'>
                  <span className='flex items-center gap-1 text-sm font-medium'>
                    <Palette className='h-3 w-3' />
                    Colour
                  </span>
                  <div
                    className='flex flex-wrap gap-1.5'
                    data-testid='colour-picker'
                  >
                    {colors.map(color => (
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
                    // Disabled mid-flight like every other control here, so the
                    // user cannot leave the create form and then have the
                    // resolving mutation reset the popover underneath them.
                    disabled={isMutating}
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
