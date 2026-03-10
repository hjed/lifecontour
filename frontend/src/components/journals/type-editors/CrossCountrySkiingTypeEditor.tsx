'use client';

import { useId } from 'react';
import { Snowflake } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { CrossCountrySkiingData } from '@/types/journals';
import {
  compactSummaryItems,
  buildRouteSummaryItem,
  RouteBackedTypeEditorLayout,
} from './RouteBackedTypeEditorLayout';
import { useRouteBackedTypeEditor } from './useRouteBackedTypeEditor';

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
  const baseId = useId();
  const routeFieldId = `${baseId}-route`;
  const snowConditionsFieldId = `${baseId}-snow-conditions`;

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
    initialData.snow_conditions
      ? {
          label: 'Snow Conditions',
          value: initialData.snow_conditions,
          fullWidth: true,
        }
      : null
  );

  return (
    <RouteBackedTypeEditorLayout
      className={className}
      testId={testId || 'cross-country-skiing-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No cross-country skiing details provided.'
      summaryItems={summaryItems}
      summaryTestId='cross-country-skiing-summary'
      routeFieldId={routeFieldId}
      routeValue={editData.route_id}
      onRouteChange={routeId =>
        setEditData(previous => ({ ...previous, route_id: routeId }))
      }
      routePlaceholder='Select a ski route...'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
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
            setEditData(previous => ({
              ...previous,
              snow_conditions: e.target.value || null,
            }))
          }
          placeholder='Describe the snow conditions...'
          data-testid='snow-conditions-input'
        />
      </div>
    </RouteBackedTypeEditorLayout>
  );
}
