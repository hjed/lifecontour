/**
 * TravelTypeEditor component for editing TRAVEL type journal data.
 *
 * Provides inline editing for travel data including flights, accommodations, and transportation.
 */

'use client';

import { useMemo } from 'react';
import { Plane, Hotel, Car } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import type { TravelData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface TravelTypeEditorProps {
  readonly journalId: string;
  readonly data?: TravelData;
  readonly onSave?: (data: TravelData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

const DEFAULT_DATA: TravelData = {
  flights: [],
  accommodations: [],
  transportation: [],
};

/**
 * TravelTypeEditor component for editing travel data.
 *
 * @example
 * ```tsx
 * <TravelTypeEditor
 *   journalId="123"
 *   data={travelData}
 *   onSave={handleSave}
 * />
 * ```
 */
export function TravelTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
}: TravelTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);

  const { isEditing, editData, handleEdit, handleSave, handleCancel } =
    useTypeEditorState({
      initialData,
      onSave,
    });

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'travel-type-editor'}
    >
      {/* Summary of travel data */}
      <div className='space-y-3'>
        <div className='flex items-center gap-2'>
          <Plane className='h-4 w-4' aria-hidden='true' />
          <Label>Flights</Label>
        </div>
        <p className='text-muted-foreground text-sm'>
          {editData.flights.length === 0
            ? 'No flights added yet'
            : `${editData.flights.length} flight(s)`}
        </p>

        <div className='flex items-center gap-2'>
          <Hotel className='h-4 w-4' aria-hidden='true' />
          <Label>Accommodations</Label>
        </div>
        <p className='text-muted-foreground text-sm'>
          {editData.accommodations.length === 0
            ? 'No accommodations added yet'
            : `${editData.accommodations.length} accommodation(s)`}
        </p>

        <div className='flex items-center gap-2'>
          <Car className='h-4 w-4' aria-hidden='true' />
          <Label>Transportation</Label>
        </div>
        <p className='text-muted-foreground text-sm'>
          {editData.transportation.length === 0
            ? 'No transportation added yet'
            : `${editData.transportation.length} transportation item(s)`}
        </p>

        <p className='text-muted-foreground text-xs italic'>
          Full travel editor with flights, accommodations, and transportation
          management will be implemented in a future iteration.
        </p>
      </div>

      {/* Edit/Save/Cancel buttons */}
      <TypeEditorActions
        isEditing={isEditing}
        onEdit={handleEdit}
        onSave={handleSave}
        onCancel={handleCancel}
      />
    </div>
  );
}
