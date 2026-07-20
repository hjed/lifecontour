'use client';

import { useId } from 'react';
import { Maximize2, MoveVertical } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import type { CavingData } from '@/types/journals';
import {
  SummaryBadgeList,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { GenericTypeEditorLayout } from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

interface CavingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: CavingData;
  readonly onSave?: (data: CavingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: CavingData) => void;
}

const DEFAULT_DATA: CavingData = {};

function buildCavingFlags(data: CavingData): string[] {
  const flags: string[] = [];
  if (data.is_vertical) flags.push('Vertical');
  if (data.is_horizontal) flags.push('Horizontal');
  return flags;
}

function buildReadOnlySummaryItems(
  data: CavingData,
  cavingFlags: string[]
): ReadOnlyTypeSummaryItem[] {
  const summaryItems: ReadOnlyTypeSummaryItem[] = [];

  if (cavingFlags.length > 0) {
    summaryItems.push({
      label: 'Flags',
      value: <SummaryBadgeList values={cavingFlags} />,
      fullWidth: true,
    });
  }

  return summaryItems;
}

export function CavingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: CavingTypeEditorProps) {
  const baseId = useId();
  const verticalFieldId = `${baseId}-vertical`;
  const horizontalFieldId = `${baseId}-horizontal`;

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

  const cavingFlags = buildCavingFlags(data ?? DEFAULT_DATA);

  const summaryItems = buildReadOnlySummaryItems(
    data ?? DEFAULT_DATA,
    cavingFlags
  );

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'caving-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No caving details provided.'
      summaryItems={summaryItems}
      summaryTestId='caving-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='flex items-center space-x-2 pt-2'>
        <Switch
          id={verticalFieldId}
          checked={editData.is_vertical ?? false}
          onCheckedChange={(checked: boolean) =>
            setEditData(previous => ({ ...previous, is_vertical: checked }))
          }
          data-testid='vertical-switch'
          disabled={!isEditing && !createMode}
        />
        <Label htmlFor={verticalFieldId} className='flex items-center gap-2'>
          <MoveVertical
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          Vertical
        </Label>
      </div>

      <div className='flex items-center space-x-2 pt-2'>
        <Switch
          id={horizontalFieldId}
          checked={editData.is_horizontal ?? false}
          onCheckedChange={(checked: boolean) =>
            setEditData(previous => ({ ...previous, is_horizontal: checked }))
          }
          data-testid='horizontal-switch'
          disabled={!isEditing && !createMode}
        />
        <Label htmlFor={horizontalFieldId} className='flex items-center gap-2'>
          <Maximize2
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          Horizontal
        </Label>
      </div>
    </GenericTypeEditorLayout>
  );
}
