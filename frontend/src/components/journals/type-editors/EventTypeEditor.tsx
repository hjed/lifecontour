/**
 * EventTypeEditor component for editing EVENT type journal data.
 *
 * Provides inline editing for calendar selection, start/end times, location,
 * all-day toggle, and sync_invitees setting.
 */

'use client';

import { useCallback, useState } from 'react';
import { Calendar as CalendarIcon, MapPin, Clock } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { CalendarInfoData } from '@/types/journals';

interface EventTypeEditorProps {
  readonly journalId: string;
  readonly data?: CalendarInfoData;
  readonly onSave?: (data: CalendarInfoData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

/**
 * EventTypeEditor component for editing event-specific data.
 *
 * @example
 * ```tsx
 * <EventTypeEditor
 *   journalId="123"
 *   data={eventData}
 *   onSave={handleSave}
 * />
 * ```
 */
export function EventTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
}: EventTypeEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<CalendarInfoData>(
    data || {
      calendar_id: '',
      is_all_day: false,
      sync_invitees: false,
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
        calendar_id: '',
        is_all_day: false,
        sync_invitees: false,
      }
    );
    setIsEditing(false);
  }, [data]);

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'event-type-editor'}
    >
      {/* Calendar Selection */}
      <div className='space-y-2'>
        <Label htmlFor='calendar-id' className='flex items-center gap-2'>
          <CalendarIcon className='h-4 w-4' aria-hidden='true' />
          Calendar
        </Label>
        <Input
          id='calendar-id'
          value={editData.calendar_id || ''}
          onChange={e =>
            setEditData({ ...editData, calendar_id: e.target.value })
          }
          placeholder='Select calendar'
          disabled={!isEditing}
          data-testid='calendar-id-input'
        />
      </div>

      {/* All-day toggle */}
      <div className='flex items-center space-x-2'>
        <Checkbox
          id='is-all-day'
          checked={editData.is_all_day}
          onCheckedChange={checked =>
            setEditData({ ...editData, is_all_day: checked as boolean })
          }
          disabled={!isEditing}
          data-testid='is-all-day-checkbox'
        />
        <Label
          htmlFor='is-all-day'
          className='cursor-pointer text-sm font-normal'
        >
          All-day event
        </Label>
      </div>

      {/* Time fields (only shown if not all-day) */}
      {!editData.is_all_day && (
        <div className='grid grid-cols-2 gap-4'>
          <div className='space-y-2'>
            <Label htmlFor='start-time' className='flex items-center gap-2'>
              <Clock className='h-4 w-4' aria-hidden='true' />
              Start Time
            </Label>
            <Input
              id='start-time'
              type='time'
              value={editData.start_time || ''}
              onChange={e =>
                setEditData({ ...editData, start_time: e.target.value })
              }
              disabled={!isEditing}
              data-testid='start-time-input'
            />
          </div>
          <div className='space-y-2'>
            <Label htmlFor='end-time'>End Time</Label>
            <Input
              id='end-time'
              type='time'
              value={editData.end_time || ''}
              onChange={e =>
                setEditData({ ...editData, end_time: e.target.value })
              }
              disabled={!isEditing}
              data-testid='end-time-input'
            />
          </div>
        </div>
      )}

      {/* Location */}
      <div className='space-y-2'>
        <Label htmlFor='location' className='flex items-center gap-2'>
          <MapPin className='h-4 w-4' aria-hidden='true' />
          Location
        </Label>
        <Input
          id='location'
          value={editData.location || ''}
          onChange={e => setEditData({ ...editData, location: e.target.value })}
          placeholder='Add location'
          disabled={!isEditing}
          data-testid='location-input'
        />
      </div>

      {/* Sync invitees */}
      <div className='flex items-center space-x-2'>
        <Checkbox
          id='sync-invitees'
          checked={editData.sync_invitees}
          onCheckedChange={checked =>
            setEditData({ ...editData, sync_invitees: checked as boolean })
          }
          disabled={!isEditing}
          data-testid='sync-invitees-checkbox'
        />
        <Label
          htmlFor='sync-invitees'
          className='cursor-pointer text-sm font-normal'
        >
          Sync invitees to calendar
        </Label>
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
