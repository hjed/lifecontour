'use client';

import { useId, useState } from 'react';
import { Target, Plus, X } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { OutdoorTrainingData } from '@/types/journals';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

interface OutdoorTrainingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: OutdoorTrainingData;
  readonly onSave?: (data: OutdoorTrainingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: OutdoorTrainingData) => void;
}

const DEFAULT_DATA: OutdoorTrainingData = {};

const KNOWN_ACTIVITY_TYPES = [
  { value: 'abseiling_trip', label: 'Abseiling' },
  { value: 'bushwalking', label: 'Bushwalking' },
  { value: 'canoeing', label: 'Canoeing' },
  { value: 'canyoning', label: 'Canyoning' },
  { value: 'caving', label: 'Caving' },
  { value: 'climbing', label: 'Climbing' },
  { value: 'cross_country_skiing', label: 'Cross-Country Skiing' },
  { value: 'diving', label: 'Diving' },
  { value: 'downhill_skiing', label: 'Downhill Skiing' },
  { value: 'kayaking', label: 'Kayaking' },
  { value: 'snorkelling', label: 'Snorkelling' },
];

export function OutdoorTrainingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: OutdoorTrainingTypeEditorProps) {
  const baseId = useId();
  const [customFocusArea, setCustomFocusArea] = useState('');

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
    data?.focus_areas && data.focus_areas.length > 0
      ? {
          label: 'Focus Areas',
          value: data.focus_areas
            .map(area => {
              const knownType = KNOWN_ACTIVITY_TYPES.find(
                t => t.value === area
              );
              return knownType ? knownType.label : area;
            })
            .join(', '),
        }
      : null
  );

  const handleAddCustomFocusArea = () => {
    const trimmed = customFocusArea.trim();
    if (!trimmed) return;

    const current = editData.focus_areas ?? [];
    if (!current.includes(trimmed)) {
      setEditData(prev => ({
        ...prev,
        focus_areas: [...current, trimmed],
      }));
    }
    setCustomFocusArea('');
  };

  const handleRemoveFocusArea = (areaToRemove: string) => {
    const current = editData.focus_areas ?? [];
    const next = current.filter(area => area !== areaToRemove);
    setEditData(prev => ({
      ...prev,
      focus_areas: next.length > 0 ? next : null,
    }));
  };

  const handleToggleKnownActivity = (value: string, checked: boolean) => {
    const current = editData.focus_areas ?? [];
    let next;
    if (checked) {
      if (!current.includes(value)) {
        next = [...current, value];
      } else {
        next = current;
      }
    } else {
      next = current.filter(v => v !== value);
    }
    setEditData(prev => ({
      ...prev,
      focus_areas: next.length > 0 ? next : null,
    }));
  };

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'outdoor-training-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No outdoor training details provided.'
      summaryItems={summaryItems}
      summaryTestId='outdoor-training-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='space-y-6'>
        <div className='space-y-3'>
          <Label className='flex items-center gap-2'>
            <Target
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Focus Areas
          </Label>

          {/* Selected Focus Areas Display */}
          {(editData.focus_areas?.length ?? 0) > 0 && (
            <div className='mb-4 flex flex-wrap gap-2'>
              {editData.focus_areas?.map(area => {
                const knownType = KNOWN_ACTIVITY_TYPES.find(
                  t => t.value === area
                );
                const displayLabel = knownType ? knownType.label : area;

                return (
                  <Badge
                    key={area}
                    variant='secondary'
                    className='flex items-center gap-1 py-1'
                  >
                    {displayLabel}
                    {(isEditing || createMode) && (
                      <button
                        type='button'
                        onClick={() => handleRemoveFocusArea(area)}
                        className='text-muted-foreground hover:text-foreground ml-1 outline-none'
                        aria-label={`Remove ${displayLabel}`}
                        data-testid={`remove-focus-area-${area}`}
                      >
                        <X className='h-3 w-3' />
                      </button>
                    )}
                  </Badge>
                );
              })}
            </div>
          )}

          {(isEditing || createMode) && (
            <div className='space-y-4'>
              {/* Custom Focus Area Input */}
              <div className='flex gap-2'>
                <Input
                  value={customFocusArea}
                  onChange={e => setCustomFocusArea(e.target.value)}
                  placeholder='Add custom focus area (e.g. Navigation, Wilderness First Aid)...'
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddCustomFocusArea();
                    }
                  }}
                  data-testid='custom-focus-area-input'
                />
                <Button
                  type='button'
                  variant='secondary'
                  onClick={handleAddCustomFocusArea}
                  disabled={!customFocusArea.trim()}
                  data-testid='add-focus-area-btn'
                >
                  <Plus className='mr-1 h-4 w-4' /> Add
                </Button>
              </div>

              <div className='text-muted-foreground pt-2 text-sm'>
                Or select from known activity types:
              </div>
              <div className='grid grid-cols-2 gap-3 sm:grid-cols-3'>
                {KNOWN_ACTIVITY_TYPES.map(subtype => {
                  const isChecked =
                    editData.focus_areas?.includes(subtype.value) ?? false;
                  return (
                    <div
                      key={subtype.value}
                      className='flex items-center space-x-2'
                    >
                      <Checkbox
                        id={`${baseId}-${subtype.value}`}
                        checked={isChecked}
                        onCheckedChange={checked =>
                          handleToggleKnownActivity(subtype.value, !!checked)
                        }
                        data-testid={`focus-area-checkbox-${subtype.value}`}
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
          )}
        </div>
      </div>
    </GenericTypeEditorLayout>
  );
}
