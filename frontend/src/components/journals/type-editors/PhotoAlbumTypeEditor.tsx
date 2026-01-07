/**
 * PhotoAlbumTypeEditor component for editing PHOTO_ALBUM type journal data.
 *
 * Provides inline editing for Immich album ID input.
 * Prepared for future album picker integration.
 */

'use client';

import { useCallback, useState } from 'react';
import { Image } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { PhotoAlbumData } from '@/types/journals';

interface PhotoAlbumTypeEditorProps {
  readonly journalId: string;
  readonly data?: PhotoAlbumData;
  readonly onSave?: (data: PhotoAlbumData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

/**
 * PhotoAlbumTypeEditor component for editing photo album data.
 *
 * @example
 * ```tsx
 * <PhotoAlbumTypeEditor
 *   journalId="123"
 *   data={photoAlbumData}
 *   onSave={handleSave}
 * />
 * ```
 */
export function PhotoAlbumTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
}: PhotoAlbumTypeEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<PhotoAlbumData>(
    data || {
      immich_album_id: null,
    }
  );

  const handleSave = useCallback(async () => {
    if (onSave) {
      await onSave(editData);
      setIsEditing(false);
    }
  }, [editData, onSave]);

  const handleCancel = useCallback(() => {
    setEditData(
      data || {
        immich_album_id: null,
      }
    );
    setIsEditing(false);
  }, [data]);

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'photo-album-type-editor'}
    >
      {/* Immich Album ID */}
      <div className='space-y-2'>
        <Label htmlFor='immich-album-id' className='flex items-center gap-2'>
          {/* eslint-disable-next-line jsx-a11y/alt-text */}
          <Image className='h-4 w-4' aria-hidden='true' />
          Immich Album ID
        </Label>
        <Input
          id='immich-album-id'
          value={editData.immich_album_id || ''}
          onChange={e =>
            setEditData({
              ...editData,
              immich_album_id: e.target.value || null,
            })
          }
          placeholder='Enter Immich album ID'
          disabled={!isEditing}
          data-testid='immich-album-id-input'
        />
        <p className='text-muted-foreground text-xs'>
          Future: Album picker will be integrated here
        </p>
      </div>

      {/* Edit/Save/Cancel buttons */}
      <div className='flex gap-2'>
        {!isEditing ? (
          <Button
            variant='outline'
            size='sm'
            onClick={() => setIsEditing(true)}
            data-testid='edit-button'
          >
            Edit
          </Button>
        ) : (
          <>
            <Button
              variant='default'
              size='sm'
              onClick={handleSave}
              data-testid='save-button'
            >
              Save
            </Button>
            <Button
              variant='outline'
              size='sm'
              onClick={handleCancel}
              data-testid='cancel-button'
            >
              Cancel
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
