'use client';

import { useMemo } from 'react';
import { Activity, Flame, Heart, Ruler, Timer, Mountain } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { FitnessData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';
import { ActivityStats } from '../ActivityStats';
import { GPXTrackDisplay } from '../GPXTrackDisplay';
import { JournalRoutesEditor } from '../JournalRoutesEditor';

interface FitnessTypeEditorProps {
  readonly journalId?: string;
  readonly data?: FitnessData;
  readonly onSave?: (data: FitnessData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: FitnessData) => void;
}

const DEFAULT_DATA: FitnessData = {};

/**
 * FitnessTypeEditor component for editing fitness-specific data.
 *
 * @example
 * ```tsx
 * <FitnessTypeEditor
 *   journalId="123"
 *   data={fitnessData}
 *   onSave={handleSave}
 * />
 * ```
 */
export function FitnessTypeEditor({
  journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: FitnessTypeEditorProps) {
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

  const handlePendingRoutesChange = (
    routes: { name: string; gpx_data: string }[]
  ) => {
    setEditData(previous => ({ ...previous, pending_routes: routes }));
  };

  const updateNumberField = (field: keyof FitnessData, value: string) => {
    if (value === '') {
      setEditData(previous => ({ ...previous, [field]: null }));
      return;
    }
    const parsedValue = Number.parseInt(value, 10);
    setEditData(previous => ({
      ...previous,
      [field]: Number.isNaN(parsedValue) ? null : parsedValue,
    }));
  };

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'fitness-type-editor'}
    >
      {journalId && !createMode && <GPXTrackDisplay journalId={journalId} />}

      {isEditing || createMode ? (
        <div className='grid grid-cols-2 gap-4'>
          {/* Distance */}
          <div className='space-y-2'>
            <Label htmlFor='distance' className='flex items-center gap-2'>
              <Ruler
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Distance (meters)
            </Label>
            <Input
              id='distance'
              type='number'
              value={editData.distance ?? ''}
              onChange={e => updateNumberField('distance', e.target.value)}
              disabled={!isEditing}
              data-testid='distance-input'
              min={0}
            />
          </div>

          {/* Duration */}
          <div className='space-y-2'>
            <Label htmlFor='duration' className='flex items-center gap-2'>
              <Timer
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Duration (seconds)
            </Label>
            <Input
              id='duration'
              type='number'
              value={editData.duration ?? ''}
              onChange={e => updateNumberField('duration', e.target.value)}
              disabled={!isEditing}
              data-testid='duration-input'
              min={0}
            />
          </div>

          {/* Heart Rate Avg */}
          <div className='space-y-2'>
            <Label htmlFor='hr-avg' className='flex items-center gap-2'>
              <Heart
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Avg Heart Rate (bpm)
            </Label>
            <Input
              id='hr-avg'
              type='number'
              value={editData.heart_rate_avg ?? ''}
              onChange={e =>
                updateNumberField('heart_rate_avg', e.target.value)
              }
              disabled={!isEditing}
              data-testid='hr-avg-input'
              min={0}
            />
          </div>

          {/* Elevation Gain */}
          <div className='space-y-2'>
            <Label htmlFor='elevation-gain' className='flex items-center gap-2'>
              <Mountain
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Elevation Gain (m)
            </Label>
            <Input
              id='elevation-gain'
              type='number'
              value={editData.elevation_gain ?? ''}
              onChange={e =>
                updateNumberField('elevation_gain', e.target.value)
              }
              disabled={!isEditing}
              data-testid='elevation-gain-input'
              min={0}
            />
          </div>

          {/* Calories */}
          <div className='space-y-2'>
            <Label htmlFor='calories' className='flex items-center gap-2'>
              <Flame
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Calories (kcal)
            </Label>
            <Input
              id='calories'
              type='number'
              value={editData.calories ?? ''}
              onChange={e => updateNumberField('calories', e.target.value)}
              disabled={!isEditing}
              data-testid='calories-input'
              min={0}
            />
          </div>

          {/* Strava ID */}
          <div className='space-y-2'>
            <Label htmlFor='strava-id' className='flex items-center gap-2'>
              <Activity
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Strava Activity ID
            </Label>
            <Input
              id='strava-id'
              type='text'
              value={editData.strava_activity_id ?? ''}
              onChange={e =>
                setEditData(previous => ({
                  ...previous,
                  strava_activity_id: e.target.value || null,
                }))
              }
              disabled={!isEditing}
              data-testid='strava-id-input'
            />
          </div>
        </div>
      ) : (
        <ActivityStats data={initialData} />
      )}
      {/* GPX Tracks Manager */}
      <JournalRoutesEditor
        createMode={createMode}
        journalId={journalId}
        pendingRoutes={editData.pending_routes}
        onPendingRoutesChange={handlePendingRoutesChange}
        isEditing={isEditing}
      />

      {/* Edit/Save/Cancel buttons */}
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
