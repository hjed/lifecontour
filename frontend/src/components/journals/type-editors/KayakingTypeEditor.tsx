'use client';

import { useId } from 'react';
import { Waves } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import type { KayakingData } from '@/types/journals';
import {
  compactSummaryItems,
  buildRouteSummaryItem,
  RouteBackedTypeEditorLayout,
} from './RouteBackedTypeEditorLayout';
import { useRouteBackedTypeEditor } from './useRouteBackedTypeEditor';

interface KayakingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: KayakingData;
  readonly onSave?: (data: KayakingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: KayakingData) => void;
}

const DEFAULT_DATA: KayakingData = {};

export function KayakingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: KayakingTypeEditorProps) {
  const baseId = useId();
  const routeFieldId = `${baseId}-route`;
  const waterTypeFieldId = `${baseId}-water-type`;

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
    initialData.water_type
      ? {
          label: 'Water Type',
          value: initialData.water_type,
        }
      : null
  );

  return (
    <RouteBackedTypeEditorLayout
      className={className}
      testId={testId || 'kayaking-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No kayaking details provided.'
      summaryItems={summaryItems}
      summaryTestId='kayaking-summary'
      routeFieldId={routeFieldId}
      routeValue={editData.route_id}
      onRouteChange={routeId =>
        setEditData(previous => ({ ...previous, route_id: routeId }))
      }
      routePlaceholder='Select a paddling route...'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='space-y-2'>
        <Label htmlFor={waterTypeFieldId} className='flex items-center gap-2'>
          <Waves className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          Water Type
        </Label>
        <Input
          id={waterTypeFieldId}
          type='text'
          value={editData.water_type ?? ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              water_type: e.target.value || null,
            }))
          }
          placeholder='e.g. river, lake, sea'
          data-testid='water-type-input'
        />
      </div>
    </RouteBackedTypeEditorLayout>
  );
}
