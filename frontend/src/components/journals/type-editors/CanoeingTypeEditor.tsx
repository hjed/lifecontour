'use client';

import { useId } from 'react';
import { Waves } from 'lucide-react';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { CanoeingData } from '@/types/journals';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

interface CanoeingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: CanoeingData;
  readonly onSave?: (data: CanoeingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: CanoeingData) => void;
}

const DEFAULT_DATA: CanoeingData = {};

const WATER_TYPES = ['river', 'lake', 'sea'] as const;

export function CanoeingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: CanoeingTypeEditorProps) {
  const baseId = useId();
  const waterTypeFieldId = `${baseId}-water-type`;

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
          value:
            data.water_type.charAt(0).toUpperCase() + data.water_type.slice(1),
        }
      : null
  );

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'canoeing-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No canoeing details provided.'
      summaryItems={summaryItems}
      summaryTestId='canoeing-summary'
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
          <Select
            value={editData.water_type ?? 'none'}
            onValueChange={value =>
              setEditData(previous => ({
                ...previous,
                water_type: value === 'none' ? null : value,
              }))
            }
          >
            <SelectTrigger id={waterTypeFieldId} data-testid='water-type-input'>
              <SelectValue placeholder='Select water type' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='none'>None</SelectItem>
              {WATER_TYPES.map(type => (
                <SelectItem key={type} value={type}>
                  {type.charAt(0).toUpperCase() + type.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </GenericTypeEditorLayout>
  );
}
