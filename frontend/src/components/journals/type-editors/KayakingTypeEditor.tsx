'use client';

import { useId } from 'react';
import { Waves } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { KayakingData } from '@/types/journals';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

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
  const waterTypeFieldId = `${baseId}-water-type`;
  const whiteWaterFieldId = `${baseId}-white-water`;
  const rapidsGradeFieldId = `${baseId}-rapids-grade`;

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
    data?.water_type
      ? {
          label: 'Water Type',
          value: data.water_type,
        }
      : null,
    data?.is_white_water
      ? {
          label: 'White Water',
          value: 'Yes',
        }
      : null,
    data?.rapids_grade
      ? {
          label: 'Rapids Grade',
          value: data.rapids_grade,
        }
      : null
  );

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'kayaking-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No kayaking details provided.'
      summaryItems={summaryItems}
      summaryTestId='kayaking-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='space-y-4'>
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
              setEditData(previous => ({
                ...previous,
                water_type: e.target.value || null,
              }))
            }
            placeholder='e.g. river, lake, sea'
            data-testid='water-type-input'
          />
        </div>

        <div className='flex items-center space-x-2'>
          <Checkbox
            id={whiteWaterFieldId}
            checked={!!editData.is_white_water}
            onCheckedChange={checked =>
              setEditData(prev => ({
                ...prev,
                is_white_water: checked === true,
                ...(checked !== true ? { rapids_grade: null } : {}),
              }))
            }
            data-testid='is-white-water-input'
          />
          <Label
            htmlFor={whiteWaterFieldId}
            className='text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
          >
            White Water Kayaking
          </Label>
        </div>

        {editData.is_white_water && (
          <div className='space-y-2'>
            <Label htmlFor={rapidsGradeFieldId}>Rapids Grade</Label>
            <Select
              value={editData.rapids_grade ?? ''}
              onValueChange={value =>
                setEditData(prev => ({
                  ...prev,
                  rapids_grade: value || null,
                }))
              }
            >
              <SelectTrigger
                id={rapidsGradeFieldId}
                data-testid='rapids-grade-input'
              >
                <SelectValue placeholder='Select grade' />
              </SelectTrigger>
              <SelectContent>
                {['I', 'II', 'III', 'IV', 'V', 'VI'].map(grade => (
                  <SelectItem key={grade} value={grade}>
                    Grade {grade}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    </GenericTypeEditorLayout>
  );
}
