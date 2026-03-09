'use client';

import { useId } from 'react';
import { Compass, Map as MapIcon, Ruler } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { ClimbingData } from '@/types/journals';
import { RouteSelector } from '@/components/routes/RouteSelector';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { TypeEditorActions } from './TypeEditorActions';
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

  if (!isEditing && !createMode) {
    const hasData =
      initialData.route_id ||
      initialData.climbing_type ||
      initialData.grade != null ||
      initialData.length != null;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No climbing details provided.
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

    const summaryItems: ReadOnlyTypeSummaryItem[] = [];

    if (initialData.route_id) {
      summaryItems.push({
        label: 'Route',
        value: routeName ?? initialData.route_id,
      });
    }

    if (initialData.climbing_type) {
      summaryItems.push({
        label: 'Climbing Type',
        value: initialData.climbing_type,
      });
    }

    if (initialData.grade != null) {
      summaryItems.push({
        label: 'Grade',
        value: initialData.grade,
      });
    }

    if (initialData.length != null) {
      summaryItems.push({
        label: 'Length',
        value: `${initialData.length} m`,
      });
    }

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'climbing-type-editor'}
      >
        <ReadOnlyTypeSummary items={summaryItems} testId='climbing-summary' />
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
      data-testid={testId || 'climbing-type-editor'}
    >
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
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
            placeholder='Select a climbing route...'
          />
        </div>

        <div className='space-y-2'>
          <Label htmlFor={climbingTypeFieldId}>Climbing Type</Label>
          <Select
            value={editData.climbing_type ?? 'none'}
            onValueChange={value =>
              setEditData({
                ...editData,
                climbing_type: value === 'none' ? null : value,
              })
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
              setEditData({
                ...editData,
                grade:
                  e.target.value === ''
                    ? null
                    : Number.parseInt(e.target.value, 10),
              })
            }
            data-testid='climbing-grade-input'
          />
        </div>

        <div className='space-y-2'>
          <Label
            htmlFor={climbingLengthFieldId}
            className='flex items-center gap-2'
          >
            <Ruler
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Length (m)
          </Label>
          <Input
            id={climbingLengthFieldId}
            type='number'
            value={editData.length ?? ''}
            onChange={e =>
              setEditData({
                ...editData,
                length:
                  e.target.value === ''
                    ? null
                    : Number.parseInt(e.target.value, 10),
              })
            }
            data-testid='climbing-length-input'
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
