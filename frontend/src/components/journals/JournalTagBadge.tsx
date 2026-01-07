/**
 * JournalTagBadge component for displaying and managing tags.
 *
 * Shows tag badges with inline add/remove functionality.
 */

'use client';

import { useState } from 'react';
import { Tag, X, Plus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { JournalTag } from '@/types/journals';

interface JournalTagBadgeProps {
  readonly tags: JournalTag[];
  readonly onTagAdd?: (tagId: number) => Promise<void>;
  readonly onTagRemove?: (tagId: number) => Promise<void>;
  readonly availableTags?: JournalTag[];
  readonly disabled?: boolean;
  readonly className?: string;
}

/**
 * Tag badge component with inline add/remove functionality.
 * Displays tag names with remove buttons.
 */
export function JournalTagBadge({
  tags,
  onTagAdd,
  onTagRemove,
  availableTags = [],
  disabled = false,
  className,
}: JournalTagBadgeProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [selectedTagId, setSelectedTagId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleAddTag = async () => {
    if (!onTagAdd || !selectedTagId) return;

    setIsLoading(true);
    try {
      await onTagAdd(selectedTagId);
      setIsAddOpen(false);
      setSelectedTagId(null);
    } catch (error) {
      console.error('Failed to add tag:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveTag = async (tagId: number) => {
    if (!onTagRemove) return;

    setIsLoading(true);
    try {
      await onTagRemove(tagId);
    } catch (error) {
      console.error('Failed to remove tag:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const canEdit = !disabled && (onTagAdd || onTagRemove);

  // Filter out already assigned tags from available tags
  const unassignedTags = availableTags.filter(
    tag => !tags.some(existing => existing.id === tag.id)
  );

  return (
    <div
      className={cn('flex flex-wrap items-center gap-2', className)}
      data-testid='tag-badges'
    >
      {/* Existing Tag Badges */}
      {tags.map(tag => (
        <Badge
          key={tag.id}
          variant='outline'
          className='gap-1.5 pr-1 text-xs'
          data-testid={`tag-badge-${tag.id}`}
        >
          <Tag className='h-3 w-3' />
          <span>{tag.name}</span>
          {onTagRemove && (
            <button
              type='button'
              onClick={() => handleRemoveTag(Number(tag.id))}
              disabled={disabled || isLoading}
              className='hover:bg-muted ml-1 rounded-sm p-0.5 transition-colors'
              aria-label={`Remove tag ${tag.name}`}
              data-testid={`remove-tag-${tag.id}`}
            >
              <X className='h-3 w-3' />
            </button>
          )}
        </Badge>
      ))}

      {/* Add Tag Button */}
      {canEdit && onTagAdd && unassignedTags.length > 0 && (
        <Popover open={isAddOpen} onOpenChange={setIsAddOpen}>
          <PopoverTrigger asChild>
            <Button
              variant='outline'
              size='sm'
              className='h-6 gap-1 text-xs'
              disabled={disabled || isLoading}
              data-testid='add-tag-button'
            >
              <Plus className='h-3 w-3' />
              Add Tag
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-64 p-3' align='start'>
            <div className='space-y-3'>
              <div className='space-y-2'>
                <label className='text-sm font-medium'>Select Tag</label>
                <Select
                  value={selectedTagId?.toString()}
                  onValueChange={value => setSelectedTagId(Number(value))}
                  disabled={isLoading}
                >
                  <SelectTrigger data-testid='tag-select'>
                    <SelectValue placeholder='Choose a tag' />
                  </SelectTrigger>
                  <SelectContent>
                    {unassignedTags.map(tag => (
                      <SelectItem key={tag.id} value={tag.id.toString()}>
                        {tag.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                onClick={handleAddTag}
                disabled={!selectedTagId || isLoading}
                className='w-full'
                size='sm'
              >
                Add
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
