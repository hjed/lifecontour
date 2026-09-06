/**
 * EventTypeEditor component for editing EVENT type journal data.
 *
 * Provides inline editing for calendar selection, start/end times, location,
 * all-day toggle, event state, and sync_invitees setting.
 */

'use client';

import { useEffect, useMemo, useRef } from 'react';
import {
  Calendar as CalendarIcon,
  MapPin,
  Clock,
  Globe,
  CircleCheck,
  FileText,
} from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useCalendars } from '@/lib/api/journals';
import { cn } from '@/lib/utils';
import { EventState } from '@/types/journals';
import type { CalendarInfoData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';
import { useUserTimezone } from '@/lib/api/settings';

const EVENT_STATE_OPTIONS: { value: EventState; label: string }[] = [
  { value: EventState.CONFIRMED, label: 'Confirmed' },
  { value: EventState.TENTATIVE, label: 'Tentative' },
  { value: EventState.INVITED, label: 'Invited' },
  { value: EventState.CANCELLED, label: 'Cancelled' },
];

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
  private_description: false,
  description: '',
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
  // The user's **configured** zone, not the browser's cached guess: it is the
  // zone the new journal's date-range bounds will be anchored in, and the two
  // have to agree or the backend reads the event a day out (issue #1401).
  const userTimezone = useUserTimezone();

  const initialData = useMemo(() => {
    if (data) return data;
    // In create mode, default timezone to user preference
    return createMode
      ? { ...DEFAULT_DATA, timezone: userTimezone }
      : DEFAULT_DATA;
  }, [data, createMode, userTimezone]);

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

  /**
   * Whether the zone in the field is the user's own doing.
   *
   * `useTypeEditorState` seeds its state once and reports it to the parent form
   * once, so a configured zone that arrives *after* this editor mounted would
   * otherwise never reach either — the new journal would be recorded, and its
   * date bounds anchored, in the fallback zone the first render had to guess.
   * Held to the same rule as the date picker: what the user has not chosen
   * follows the resolved zone, what they have chosen stands.
   */
  const timezoneChosen = useRef(Boolean(data?.timezone));

  useEffect(() => {
    if (!createMode || timezoneChosen.current) return;
    if (editData.timezone === userTimezone) return;

    setEditData(previous => ({ ...previous, timezone: userTimezone }));
  }, [createMode, editData.timezone, setEditData, userTimezone]);

  const {
    data: calendarsResponse,
    isLoading: isLoadingCalendars,
    error: calendarsError,
  } = useCalendars();
  const availableCalendars = calendarsResponse?.data || [];
  const hasNoCalendars = availableCalendars.length === 0;

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
        <Select
          value={editData.calendar_id || ''}
          onValueChange={value =>
            setEditData(previous => ({
              ...previous,
              calendar_id: value,
            }))
          }
          disabled={!isEditing || isLoadingCalendars || !!calendarsError}
        >
          <SelectTrigger id='calendar-id' data-testid='calendar-id-input'>
            <SelectValue
              placeholder={
                calendarsError
                  ? 'Failed to load calendars'
                  : hasNoCalendars && !isLoadingCalendars
                    ? 'No calendars available'
                    : 'Select calendar'
              }
            />
          </SelectTrigger>
          <SelectContent>
            {hasNoCalendars && !isLoadingCalendars && (
              <SelectItem
                value='none'
                disabled
                className='text-muted-foreground'
              >
                {calendarsError
                  ? 'Failed to load calendars'
                  : 'No calendars available'}
              </SelectItem>
            )}
            {availableCalendars.map(cal => (
              <SelectItem key={cal.id} value={cal.id}>
                <div className='flex items-center gap-2'>
                  <div
                    className='h-3 w-3 rounded-full'
                    style={{
                      backgroundColor: cal.attributes.color || '#6b7280',
                    }}
                    aria-hidden='true'
                  />
                  <span>{cal.attributes.name}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isEditing && hasNoCalendars && !isLoadingCalendars && (
          <p className='text-destructive mt-1 text-sm'>
            {calendarsError
              ? 'There was an error loading your calendars. Please try again later.'
              : 'You must create a calendar first before you can associate an event with it.'}
          </p>
        )}
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

      {/* Description */}
      <div className='space-y-2'>
        <Label htmlFor='description' className='flex items-center gap-2'>
          <FileText className='h-4 w-4' aria-hidden='true' />
          Public Description
        </Label>
        <Textarea
          id='description'
          value={editData.description || ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              description: e.target.value,
            }))
          }
          placeholder='Add description that will sync to external calendar'
          disabled={!isEditing}
          data-testid='description-textarea'
          className='min-h-[80px]'
        />
      </div>

      {/* Timezone */}
      {!editData.is_all_day && (
        <div className='space-y-2'>
          <Label htmlFor='timezone' className='flex items-center gap-2'>
            <Globe className='h-4 w-4' aria-hidden='true' />
            Timezone
          </Label>
          <Input
            id='timezone'
            value={editData.timezone || ''}
            onChange={e => {
              timezoneChosen.current = true;
              setEditData(previous => ({
                ...previous,
                timezone: e.target.value || null,
              }));
            }}
            placeholder={Intl.DateTimeFormat().resolvedOptions().timeZone}
            disabled={!isEditing}
            data-testid='timezone-input'
          />
          {editData.timezone &&
            editData.timezone !==
              Intl.DateTimeFormat().resolvedOptions().timeZone && (
              <p className='text-muted-foreground text-xs'>
                Your local timezone:{' '}
                {Intl.DateTimeFormat().resolvedOptions().timeZone}
              </p>
            )}
        </div>
      )}

      {/* Event State (only in edit mode, not create mode) */}
      {!createMode && (
        <div className='space-y-2'>
          <Label htmlFor='event-state' className='flex items-center gap-2'>
            <CircleCheck className='h-4 w-4' aria-hidden='true' />
            Event Status
          </Label>
          <Select
            value={editData.event_state || EventState.CONFIRMED}
            onValueChange={value =>
              setEditData(previous => ({
                ...previous,
                event_state: value as EventState,
              }))
            }
            disabled={!isEditing}
          >
            <SelectTrigger id='event-state' data-testid='event-state-select'>
              <SelectValue placeholder='Select status' />
            </SelectTrigger>
            <SelectContent>
              {EVENT_STATE_OPTIONS.map(option => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

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

      {/* Private description */}
      <div className='flex items-center space-x-2'>
        <Checkbox
          id='private-description'
          checked={editData.private_description}
          onCheckedChange={checked =>
            setEditData(previous => ({
              ...previous,
              private_description: checked as boolean,
            }))
          }
          disabled={!isEditing}
          data-testid='private-description-checkbox'
        />
        <Label
          htmlFor='private-description'
          className='cursor-pointer text-sm font-normal'
        >
          Keep description private (don&apos;t sync to calendar)
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
