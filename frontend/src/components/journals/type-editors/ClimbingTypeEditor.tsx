'use client';

import { useId } from 'react';
import { Compass, Ruler } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
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
  buildRouteSummaryItem,
  RouteBackedTypeEditorLayout,
} from './RouteBackedTypeEditorLayout';
import { useRouteBackedTypeEditor } from './useRouteBackedTypeEditor';

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
const CLIMBING_TYPES = ['sport', 'trad', 'bouldering', 'top_rope', 'indoor'];

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
  const routeFieldId = `${baseId}-route`;
  const climbingTypeFieldId = `${baseId}-climbing-type`;
  const climbingGradeFieldId = `${baseId}-climbing-grade`;
  const climbingLengthFieldId = `${baseId}-climbing-length`;

  const {
    initialData,
    routeName,
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  } = useRouteBackedTypeEditor({
    data,
    defaultData: DEFAULT_DATA,
    onSave,
    createMode,
    onChange,
  });

  const summaryItems = compactSummaryItems(
    buildRouteSummaryItem(initialData.route_id, routeName),
    initialData.climbing_type
      ? {
          label: 'Climbing Type',
          value: initialData.climbing_type,
        }
      : null,
    initialData.grade != null
      ? {
          label: 'Grade',
          value: initialData.grade,
        }
      : null,
    initialData.length != null
      ? {
          label: 'Length',
          value: `${initialData.length} m`,
        }
      : null
  );

  return (
    <RouteBackedTypeEditorLayout
      className={className}
      testId={testId || 'climbing-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No climbing details provided.'
      summaryItems={summaryItems}
      summaryTestId='climbing-summary'
      routeFieldId={routeFieldId}
      routeValue={editData.route_id}
      onRouteChange={routeId =>
        setEditData(previous => ({ ...previous, route_id: routeId }))
      }
      routePlaceholder='Select a climbing route...'
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
    </RouteBackedTypeEditorLayout>
  );
}
