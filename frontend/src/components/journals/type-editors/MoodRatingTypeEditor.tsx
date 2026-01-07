/**
 * MoodRatingTypeEditor component for editing MOOD_RATING type journal data.
 *
 * Provides inline editing for mood value (1-10 slider), mood label, and energy level (1-10 slider).
 */

'use client';

import { useCallback, useState } from 'react';
import { Heart, Zap } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { MoodData } from '@/types/journals';

interface MoodRatingTypeEditorProps {
  readonly journalId: string;
  readonly data?: MoodData;
  readonly onSave?: (data: MoodData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

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
}: MoodRatingTypeEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<MoodData>(
    data || {
      mood_value: null,
      mood_label: null,
      energy_level: null,
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
        mood_value: null,
        mood_label: null,
        energy_level: null,
      }
    );
    setIsEditing(false);
  }, [data]);

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
              setEditData({
                ...editData,
                mood_value: parseInt(e.target.value, 10),
              })
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
            setEditData({ ...editData, mood_label: e.target.value || null })
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
              setEditData({
                ...editData,
                energy_level: parseInt(e.target.value, 10),
              })
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
