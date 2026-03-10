/**
 * EventTypeEditor component for editing EVENT type journal data.
 *
 * Provides inline editing for calendar selection, start/end times, location,
 * all-day toggle, and sync_invitees setting.
 */

'use client';

import { useMemo } from 'react';
import { Calendar as CalendarIcon, MapPin, Clock } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import type { CalendarInfoData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface EventTypeEditorProps {
  readonly journalId?: string;
  readonly data?: CalendarInfoData;
  readonly onSave?: (data: CalendarInfoData) => Promise<void>;
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
  readonly onChange?: (data: CalendarInfoData) => void;
}

const DEFAULT_DATA: CalendarInfoData = {
  calendar_id: '',
  is_all_day: false,
  sync_invitees: false,
};

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
  createMode = false,
  onChange,
}: EventTypeEditorProps) {
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
            setEditData(previous => ({
              ...previous,
              calendar_id: e.target.value,
            }))
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
          onCheckedChange={checked => {
            const isAllDay = checked as boolean;
            setEditData(previous => ({
              ...previous,
              is_all_day: isAllDay,
              // Clear time fields when switching to all-day
              start_time: isAllDay ? null : previous.start_time,
              end_time: isAllDay ? null : previous.end_time,
            }));
          }}
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
                setEditData(previous => ({
                  ...previous,
                  start_time: e.target.value,
                }))
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
                setEditData(previous => ({
                  ...previous,
                  end_time: e.target.value,
                }))
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
          onChange={e =>
            setEditData(previous => ({ ...previous, location: e.target.value }))
          }
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
            setEditData(previous => ({
              ...previous,
              sync_invitees: checked as boolean,
            }))
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
