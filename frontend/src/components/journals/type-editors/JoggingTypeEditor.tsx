'use client';

import { useId, useMemo, useState } from 'react';
import { Timer, Map as MapIcon } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { JoggingData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';
import { RouteSelector } from '@/components/routes/RouteSelector';
import { formatSecondsPerKm } from '../ActivityStats';
import { useRoute } from '@/lib/api/routes';

interface JoggingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: JoggingData;
  readonly onSave?: (data: JoggingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: JoggingData) => void;
}

const DEFAULT_DATA: JoggingData = {};

export function JoggingTypeEditor({
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
  journalId: _journalId,
}: JoggingTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);
  const baseId = useId();
  const paceFieldId = `${baseId}-pace`;
  const routeFieldId = `${baseId}-route`;

  // Fetch route details to display route name in read-only view
  const { data: routeData } = useRoute(initialData.route_id ?? '');
  const routeName = routeData?.data?.attributes?.name;

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

  // Track the raw user-typed pace string (e.g., "5:30") independently.
  // Initialised from `initialData.pace` once; subsequent updates come only
  // from user interaction — no effect needed, avoiding the ESLint
  // react-hooks/set-state-in-effect rule.
  const [localPace, setLocalPace] = useState<string>(() => {
    if (initialData.pace) {
      const m = Math.floor(initialData.pace / 60);
      const s = initialData.pace % 60;
      return `${m}:${s.toString().padStart(2, '0')}`;
    }
    return '';
  });

  const handlePaceChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setLocalPace(val);

    // Parse mm:ss to seconds
    const parts = val.split(':');
    let totalSeconds: number | null = null;
    if (parts.length === 2) {
      const m = Number.parseInt(parts[0], 10);
      const s = Number.parseInt(parts[1], 10);
      if (!Number.isNaN(m) && !Number.isNaN(s)) {
        totalSeconds = m * 60 + s;
      }
    } else if (parts.length === 1) {
      const v = Number.parseInt(parts[0], 10);
      if (!Number.isNaN(v)) {
        totalSeconds = v * 60; // Assume they entered minutes if no colon
      }
    }

    if (totalSeconds !== null && totalSeconds > 0) {
      setEditData({ ...editData, pace: totalSeconds });
    } else if (val === '') {
      setEditData({ ...editData, pace: null });
    }
  };

  if (!isEditing && !createMode) {
    const hasData = initialData.route_id || initialData.pace;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No jogging details provided.
          </p>
          <TypeEditorActions
            isEditing={false}
            onEdit={handleEdit}
            onSave={handleSave}
            onCancel={handleCancel}
          />
        </div>
      );
    }

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'jogging-type-editor'}
      >
        <div className='grid grid-cols-2 gap-4'>
          {initialData.pace && (
            <div>
              <span className='text-muted-foreground font-medium'>Pace: </span>
              {formatSecondsPerKm(initialData.pace)}{' '}
            </div>
          )}
          {initialData.route_id && (
            <div>
              <span className='text-muted-foreground font-medium'>Route: </span>
              <span data-testid='jogging-route-display'>
                {routeName ?? initialData.route_id}
              </span>
            </div>
          )}
        </div>
        <TypeEditorActions
          isEditing={false}
          onEdit={handleEdit}
          onSave={handleSave}
          onCancel={handleCancel}
        />
      </div>
    );
  }

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'jogging-type-editor'}
    >
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        {/* Pace */}
        <div className='space-y-2'>
          <Label htmlFor={paceFieldId} className='flex items-center gap-2'>
            <Timer
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Pace (mm:ss per km)
          </Label>
          <Input
            id={paceFieldId}
            type='text'
            value={localPace}
            onChange={handlePaceChange}
            placeholder='e.g., 5:30'
            data-testid='pace-input'
          />
        </div>

        {/* Route Selector */}
        <div className='space-y-2'>
          <Label htmlFor={routeFieldId} className='flex items-center gap-2'>
            <MapIcon
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Route
          </Label>
          <RouteSelector
            id={routeFieldId}
            value={editData.route_id ?? null}
            onChange={routeId =>
              setEditData({ ...editData, route_id: routeId })
            }
            placeholder='Select a running route...'
          />
        </div>
      </div>

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
