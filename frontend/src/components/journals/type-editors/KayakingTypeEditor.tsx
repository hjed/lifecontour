'use client';

import { useId, useMemo } from 'react';
import { Map as MapIcon, Waves } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { KayakingData } from '@/types/journals';
import { RouteSelector } from '@/components/routes/RouteSelector';
import { useRoute } from '@/lib/api/routes';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

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
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);
  const { data: routeData } = useRoute(initialData.route_id ?? '');
  const routeName = routeData?.data?.attributes?.name;
  const baseId = useId();
  const routeFieldId = `${baseId}-route`;
  const waterTypeFieldId = `${baseId}-water-type`;

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
    const hasData = initialData.route_id || initialData.water_type;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No kayaking details provided.
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

    if (initialData.water_type) {
      summaryItems.push({
        label: 'Water Type',
        value: initialData.water_type,
      });
    }

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'kayaking-type-editor'}
      >
        <ReadOnlyTypeSummary items={summaryItems} testId='kayaking-summary' />
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
      data-testid={testId || 'kayaking-type-editor'}
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
            placeholder='Select a paddling route...'
          />
        </div>

        <div className='space-y-2'>
          <Label htmlFor={waterTypeFieldId} className='flex items-center gap-2'>
            <Waves
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Water Type
          </Label>
          <Input
            id={waterTypeFieldId}
            type='text'
            value={editData.water_type ?? ''}
            onChange={e =>
              setEditData({ ...editData, water_type: e.target.value || null })
            }
            placeholder='e.g. river, lake, sea'
            data-testid='water-type-input'
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
