'use client';

import { useId } from 'react';
import { MapPin, List } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
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
          <Label className='mb-2 flex items-center gap-2'>
            <MapPin
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Activity Types
          </Label>
          <div className='grid grid-cols-2 gap-3 sm:grid-cols-3'>
            {[
              { value: 'abseiling_trip', label: 'Abseiling' },
              { value: 'bushwalking', label: 'Bushwalking' },
              { value: 'canoeing', label: 'Canoeing' },
              { value: 'canyoning', label: 'Canyoning' },
              { value: 'caving', label: 'Caving' },
              { value: 'climbing', label: 'Climbing' },
              { value: 'cross_country_skiing', label: 'Cross-Country Skiing' },
              { value: 'diving', label: 'Diving' },
              { value: 'downhill_skiing', label: 'Downhill Skiing' },
              { value: 'jogging', label: 'Jogging' },
              { value: 'kayaking', label: 'Kayaking' },
              { value: 'snorkelling', label: 'Snorkelling' },
            ].map(subtype => {
              const isChecked =
                editData.activity_types?.includes(subtype.value) ?? false;
              return (
                <div
                  key={subtype.value}
                  className='flex items-center space-x-2'
                >
                  <Checkbox
                    id={`${baseId}-${subtype.value}`}
                    checked={isChecked}
                    disabled={!isEditing && !createMode}
                    onCheckedChange={checked => {
                      const current = editData.activity_types ?? [];
                      let next;
                      if (checked) {
                        next = [...current, subtype.value];
                      } else {
                        next = current.filter(v => v !== subtype.value);
                      }
                      setEditData(prev => ({
                        ...prev,
                        activity_types: next.length > 0 ? next : null,
                      }));
                    }}
                    data-testid={`activity-type-${subtype.value}`}
                  />
                  <Label
                    htmlFor={`${baseId}-${subtype.value}`}
                    className='text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
                  >
                    {subtype.label}
                  </Label>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </GenericTypeEditorLayout>
  );
}
