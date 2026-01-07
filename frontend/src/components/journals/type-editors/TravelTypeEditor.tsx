/**
 * TravelTypeEditor component for editing TRAVEL type journal data.
 *
 * Provides inline editing for travel data including flights, accommodations, and transportation.
 */

'use client';

import { useCallback, useState } from 'react';
import { Plane, Hotel, Car } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { TravelData } from '@/types/journals';

interface TravelTypeEditorProps {
  readonly journalId: string;
  readonly data?: TravelData;
  readonly onSave?: (data: TravelData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

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
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<TravelData>(
    data || {
      flights: [],
      accommodations: [],
      transportation: [],
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
        flights: [],
        accommodations: [],
        transportation: [],
      }
    );
    setIsEditing(false);
  }, [data]);

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
