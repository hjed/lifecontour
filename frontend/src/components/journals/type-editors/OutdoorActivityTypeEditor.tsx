'use client';

import { useMemo } from 'react';
import { Cloud, Target, Users } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import type { OutdoorActivityData } from '@/types/journals';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface OutdoorActivityTypeEditorProps {
  readonly journalId?: string;
  readonly data?: OutdoorActivityData;
  readonly onSave?: (data: OutdoorActivityData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: OutdoorActivityData) => void;
}

const DEFAULT_DATA: OutdoorActivityData = {};

export function OutdoorActivityTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: OutdoorActivityTypeEditorProps) {
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

  if (!isEditing && !createMode) {
    // Rely on ActivityStats to show most data, but we can show
    // text/descriptions here if we want to augment what ActivityStats shows.
    const hasData =
      initialData.weather_conditions ||
      initialData.role ||
      initialData.participant_notes ||
      initialData.in_leadership_role;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No outdoor details provided.
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
        data-testid={testId || 'outdoor-type-editor'}
      >
        <div className='grid grid-cols-2 gap-4'>
          {initialData.weather_conditions && (
            <div>
              <span className='text-muted-foreground font-medium'>
                Weather:{' '}
              </span>
              {initialData.weather_conditions}
            </div>
          )}
          {(initialData.role || initialData.in_leadership_role) && (
            <div>
              <span className='text-muted-foreground font-medium'>Role: </span>
              {initialData.role
                ? initialData.role
                : initialData.in_leadership_role
                  ? 'Leadership role'
                  : null}
              {initialData.role &&
                initialData.in_leadership_role &&
                ' (Leadership)'}
            </div>
          )}
        </div>
        {initialData.participant_notes && (
          <div>
            <span className='text-muted-foreground font-medium'>
              Participant Notes:{' '}
            </span>
            <p className='text-muted-foreground mt-1'>
              {initialData.participant_notes}
            </p>
          </div>
        )}
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
      data-testid={testId || 'outdoor-type-editor'}
    >
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        {/* Weather Conditions */}
        <div className='space-y-2'>
          <Label
            htmlFor='weather-conditions'
            className='flex items-center gap-2'
          >
            <Cloud
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Weather Conditions
          </Label>
          <Input
            id='weather-conditions'
            type='text'
            value={editData.weather_conditions ?? ''}
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                weather_conditions: e.target.value || null,
              }))
            }
            placeholder='e.g., Sunny, 22°C'
            data-testid='weather-conditions-input'
          />
        </div>

        {/* Role */}
        <div className='space-y-2'>
          <Label htmlFor='role' className='flex items-center gap-2'>
            <Target
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Role
          </Label>
          <Input
            id='role'
            type='text'
            value={editData.role ?? ''}
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                role: e.target.value || null,
              }))
            }
            placeholder='e.g., Participant, Guide'
            data-testid='role-input'
          />
        </div>

        {/* Leadership Role */}
        <div className='flex items-center space-x-2 pt-8'>
          <Switch
            id='leadership-role'
            checked={editData.in_leadership_role ?? false}
            onCheckedChange={(checked: boolean) =>
              setEditData(previous => ({
                ...previous,
                in_leadership_role: checked,
              }))
            }
            data-testid='leadership-role-switch'
          />
          <Label htmlFor='leadership-role' className='font-normal'>
            In Leadership Role
          </Label>
        </div>
      </div>

      {/* Participant Notes */}
      <div className='space-y-2'>
        <Label htmlFor='participant-notes' className='flex items-center gap-2'>
          <Users className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          Participant Notes
        </Label>
        <Textarea
          id='participant-notes'
          value={editData.participant_notes ?? ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              participant_notes: e.target.value || null,
            }))
          }
          placeholder='Notes about other participants...'
          className='min-h-[100px]'
          data-testid='participant-notes-input'
        />
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
