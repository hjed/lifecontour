/**
 * PhotoAlbumTypeEditor component for editing PHOTO_ALBUM type journal data.
 *
 * Provides inline editing for Immich album ID input.
 * Prepared for future album picker integration.
 */

'use client';

import { useMemo } from 'react';
import { Image as ImageIcon } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { PhotoAlbumData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface PhotoAlbumTypeEditorProps {
  readonly journalId?: string;
  readonly data?: PhotoAlbumData;
  readonly onSave?: (data: PhotoAlbumData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  /**
   * When true, the editor is always in edit mode (for use in create forms).
   * The TypeEditorActions (Edit/Save/Cancel) buttons are hidden.
   */
  readonly createMode?: boolean;
  /**
   * Called whenever the data changes in create mode.
   * Used by parent create forms to collect type-specific data.
   */
  readonly onChange?: (data: PhotoAlbumData) => void;
}

const DEFAULT_DATA: PhotoAlbumData = {
  immich_album_id: null,
};

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
  createMode = false,
  onChange,
}: PhotoAlbumTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);

  const {
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  } = useTypeEditorState({
    initialData,
    onSave,
    createMode,
    onChange,
  });

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'photo-album-type-editor'}
    >
      {/* Immich Album ID */}
      <div className='space-y-2'>
        <Label htmlFor='immich-album-id' className='flex items-center gap-2'>
          <ImageIcon className='h-4 w-4' aria-hidden='true' />
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

      {/* Edit/Save/Cancel buttons (hidden in create mode) */}
      {!createMode && (
        <TypeEditorActions
          isEditing={isEditing}
          onEdit={handleEdit}
          onSave={handleSave}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}
