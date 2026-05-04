'use client';

import { useId } from 'react';
import { MapPin, List } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { OutdoorPlanningData } from '@/types/journals';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

interface OutdoorPlanningTypeEditorProps {
  readonly journalId?: string;
  readonly data?: OutdoorPlanningData;
  readonly onSave?: (data: OutdoorPlanningData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: OutdoorPlanningData) => void;
}

const DEFAULT_DATA: OutdoorPlanningData = {};

export function OutdoorPlanningTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: OutdoorPlanningTypeEditorProps) {
  const baseId = useId();
  const topicsFieldId = `${baseId}-topics`;
  const activityTypesFieldId = `${baseId}-activity-types`;

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
    data?.topics
      ? {
          label: 'Topics',
          value: data.topics,
        }
      : null,
    data?.activity_types && data.activity_types.length > 0
      ? {
          label: 'Activity Types',
          value: data.activity_types.join(', '),
        }
      : null
  );

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'outdoor-planning-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No outdoor planning details provided.'
      summaryItems={summaryItems}
      summaryTestId='outdoor-planning-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='space-y-4'>
        <div className='space-y-2'>
          <Label htmlFor={topicsFieldId} className='flex items-center gap-2'>
            <List
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Topics
          </Label>
          <Textarea
            id={topicsFieldId}
            data-testid='topics-input'
            value={editData.topics ?? ''}
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                topics: e.target.value || null,
              }))
            }
            disabled={!isEditing && !createMode}
            placeholder='Logistics, gear list, weather...'
          />
        </div>

        <div className='space-y-2'>
          <Label
            htmlFor={activityTypesFieldId}
            className='flex items-center gap-2'
          >
            <MapPin
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Activity Types (comma separated)
          </Label>
          <Input
            id={activityTypesFieldId}
            data-testid='activity-types-input'
            value={editData.activity_types?.join(', ') ?? ''}
            onChange={e => {
              const val = e.target.value;
              const types = val
                ? val
                    .split(',')
                    .map(s => s.trim())
                    .filter(Boolean)
                : null;
              setEditData(previous => ({
                ...previous,
                activity_types: types && types.length > 0 ? types : null,
              }));
            }}
            disabled={!isEditing && !createMode}
            placeholder='canyoning, bushwalking...'
          />
        </div>
      </div>
    </GenericTypeEditorLayout>
  );
}
