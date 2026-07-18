'use client';

import { useId } from 'react';
import { Compass, Ruler } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ClimbingData } from '@/types/journals';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

interface ClimbingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: ClimbingData;
  readonly onSave?: (data: ClimbingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: ClimbingData) => void;
}

const DEFAULT_DATA: ClimbingData = {};
// Mutually-exclusive climbing styles. "indoor" is intentionally NOT here — it is
// a separate boolean toggle, since a climb of any style can be indoor or outdoor.
const CLIMBING_TYPES = ['sport', 'trad', 'bouldering', 'top_rope'];

export function ClimbingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: ClimbingTypeEditorProps) {
  const baseId = useId();
  const climbingTypeFieldId = `${baseId}-climbing-type`;
  const climbingGradeFieldId = `${baseId}-climbing-grade`;
  const climbingLengthFieldId = `${baseId}-climbing-length`;
  const climbingIndoorFieldId = `${baseId}-climbing-indoor`;

  const {
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  } = useTypeEditorState({
    initialData: data ?? DEFAULT_DATA,
    onSave,
    createMode,
    onChange,
  });

  const summaryItems = compactSummaryItems(
    data?.climbing_type
      ? {
          label: 'Climbing Type',
          value: data.climbing_type,
        }
      : null,
    data?.grade == null
      ? null
      : {
          label: 'Grade',
          value: data.grade,
        },
    data?.length == null
      ? null
      : {
          label: 'Length',
          value: `${data.length} m`,
        },
    data?.indoor
      ? {
          label: 'Indoor',
          value: 'Yes',
        }
      : null
  );

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'climbing-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No climbing details provided.'
      summaryItems={summaryItems}
      summaryTestId='climbing-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='space-y-2'>
        <Label htmlFor={climbingTypeFieldId}>Climbing Type</Label>
        <Select
          value={editData.climbing_type ?? 'none'}
          onValueChange={value =>
            setEditData(previous => ({
              ...previous,
              climbing_type: value === 'none' ? null : value,
            }))
          }
        >
          <SelectTrigger id={climbingTypeFieldId} className='w-full'>
            <SelectValue placeholder='Select climbing type...' />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='none'>None</SelectItem>
            {CLIMBING_TYPES.map(type => (
              <SelectItem key={type} value={type}>
                {type}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className='space-y-2'>
        <Label
          htmlFor={climbingGradeFieldId}
          className='flex items-center gap-2'
        >
          <Compass
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          Grade
        </Label>
        <Input
          id={climbingGradeFieldId}
          type='number'
          value={editData.grade ?? ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              grade:
                e.target.value === ''
                  ? null
                  : Number.parseInt(e.target.value, 10),
            }))
          }
          data-testid='climbing-grade-input'
        />
      </div>

      <div className='space-y-2'>
        <Label
          htmlFor={climbingLengthFieldId}
          className='flex items-center gap-2'
        >
          <Ruler className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          Length (m)
        </Label>
        <Input
          id={climbingLengthFieldId}
          type='number'
          value={editData.length ?? ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              length:
                e.target.value === ''
                  ? null
                  : Number.parseInt(e.target.value, 10),
            }))
          }
          data-testid='climbing-length-input'
        />
      </div>

      <div className='flex items-center justify-between gap-2'>
        <Label htmlFor={climbingIndoorFieldId}>Indoor</Label>
        <Switch
          id={climbingIndoorFieldId}
          checked={editData.indoor ?? false}
          onCheckedChange={checked =>
            setEditData(previous => ({
              ...previous,
              indoor: checked,
            }))
          }
          data-testid='climbing-indoor-toggle'
          aria-label='Indoor'
        />
      </div>
    </GenericTypeEditorLayout>
  );
}
