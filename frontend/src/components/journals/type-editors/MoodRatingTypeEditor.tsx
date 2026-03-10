/**
 * MoodRatingTypeEditor component for editing MOOD_RATING type journal data.
 *
 * Provides inline editing for mood value (1-10 slider), mood label, and energy level (1-10 slider).
 */

'use client';

import { useMemo } from 'react';
import { Heart, Zap } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { MoodData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface MoodRatingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: MoodData;
  readonly onSave?: (data: MoodData) => Promise<void>;
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
  readonly onChange?: (data: MoodData) => void;
}

const DEFAULT_DATA: MoodData = {
  mood_value: null,
  mood_label: null,
  energy_level: null,
};

/**
 * MoodRatingTypeEditor component for editing mood and energy data.
 *
 * @example
 * ```tsx
 * <MoodRatingTypeEditor
 *   journalId="123"
 *   data={moodData}
 *   onSave={handleSave}
 * />
 * ```
 */
export function MoodRatingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: MoodRatingTypeEditorProps) {
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
    // Initialize sliders to middle value (5) if they're null when entering edit mode
    onEdit: currentData => ({
      ...currentData,
      mood_value: currentData.mood_value ?? 5,
      energy_level: currentData.energy_level ?? 5,
    }),
    createMode,
    onChange,
  });

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'mood-rating-type-editor'}
    >
      {/* Mood Value Slider */}
      <div className='space-y-2'>
        <Label htmlFor='mood-value' className='flex items-center gap-2'>
          <Heart className='h-4 w-4' aria-hidden='true' />
          Mood (1-10)
        </Label>
        <div className='flex items-center gap-4'>
          <input
            id='mood-value'
            type='range'
            min='1'
            max='10'
            value={editData.mood_value || 5}
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                mood_value: Number.parseInt(e.target.value, 10),
              }))
            }
            disabled={!isEditing}
            className='flex-1'
            data-testid='mood-value-slider'
          />
          <span
            className='text-muted-foreground min-w-[2rem] text-center text-sm font-medium'
            data-testid='mood-value-display'
          >
            {editData.mood_value || '-'}
          </span>
        </div>
      </div>

      {/* Mood Label */}
      <div className='space-y-2'>
        <Label htmlFor='mood-label'>Mood Label</Label>
        <Input
          id='mood-label'
          value={editData.mood_label || ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              mood_label: e.target.value || null,
            }))
          }
          placeholder='e.g., Happy, Anxious, Calm'
          disabled={!isEditing}
          data-testid='mood-label-input'
        />
      </div>

      {/* Energy Level Slider */}
      <div className='space-y-2'>
        <Label htmlFor='energy-level' className='flex items-center gap-2'>
          <Zap className='h-4 w-4' aria-hidden='true' />
          Energy Level (1-10)
        </Label>
        <div className='flex items-center gap-4'>
          <input
            id='energy-level'
            type='range'
            min='1'
            max='10'
            value={editData.energy_level || 5}
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                energy_level: Number.parseInt(e.target.value, 10),
              }))
            }
            disabled={!isEditing}
            className='flex-1'
            data-testid='energy-level-slider'
          />
          <span
            className='text-muted-foreground min-w-[2rem] text-center text-sm font-medium'
            data-testid='energy-level-display'
          >
            {editData.energy_level || '-'}
          </span>
        </div>
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
