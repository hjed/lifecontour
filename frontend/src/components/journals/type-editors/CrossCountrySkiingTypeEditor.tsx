'use client';

import { useId, useMemo } from 'react';
import { Map as MapIcon, Snowflake } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type { CrossCountrySkiingData } from '@/types/journals';
import { RouteSelector } from '@/components/routes/RouteSelector';
import { useRoute } from '@/lib/api/routes';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface CrossCountrySkiingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: CrossCountrySkiingData;
  readonly onSave?: (data: CrossCountrySkiingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: CrossCountrySkiingData) => void;
}

const DEFAULT_DATA: CrossCountrySkiingData = {};

export function CrossCountrySkiingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: CrossCountrySkiingTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);
  const { data: routeData } = useRoute(initialData.route_id ?? '');
  const routeName = routeData?.data?.attributes?.name;
  const baseId = useId();
  const routeFieldId = `${baseId}-route`;
  const snowConditionsFieldId = `${baseId}-snow-conditions`;

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
    const hasData = initialData.route_id || initialData.snow_conditions;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No cross-country skiing details provided.
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

    if (initialData.snow_conditions) {
      summaryItems.push({
        label: 'Snow Conditions',
        value: initialData.snow_conditions,
        fullWidth: true,
      });
    }

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'cross-country-skiing-type-editor'}
      >
        <ReadOnlyTypeSummary
          items={summaryItems}
          testId='cross-country-skiing-summary'
        />
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
      data-testid={testId || 'cross-country-skiing-type-editor'}
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
            placeholder='Select a ski route...'
          />
        </div>

        <div className='space-y-2'>
          <Label
            htmlFor={snowConditionsFieldId}
            className='flex items-center gap-2'
          >
            <Snowflake
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Snow Conditions
          </Label>
          <Textarea
            id={snowConditionsFieldId}
            value={editData.snow_conditions ?? ''}
            onChange={e =>
              setEditData({
                ...editData,
                snow_conditions: e.target.value || null,
              })
            }
            placeholder='Describe the snow conditions...'
            data-testid='snow-conditions-input'
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
