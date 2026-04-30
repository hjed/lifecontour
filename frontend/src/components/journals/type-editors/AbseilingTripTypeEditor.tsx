'use client';

import { useId, useMemo, useState } from 'react';
import { Hash, Ruler } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { AbseilingData, AbseilPitch } from '@/types/journals';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';
import { PitchEditor } from './PitchEditor';

interface AbseilingTripTypeEditorProps {
  readonly journalId?: string;
  readonly data?: AbseilingData;
  readonly onSave?: (data: AbseilingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: AbseilingData) => void;
}

const DEFAULT_DATA: AbseilingData = {};

export function AbseilingTripTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: AbseilingTripTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);
  const baseId = useId();
  const abseilsFieldId = `${baseId}-number-of-abseils`;
  const totalLengthFieldId = `${baseId}-total-length`;

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

  const initialCalcAbseils = (initialData.pitches || []).length;
  const initialCalcLength = (initialData.pitches || []).reduce(
    (sum, p) => sum + (p.height || 0),
    0
  );

  const [isManualAbseils, setIsManualAbseils] = useState<boolean>(
    initialData.number_of_abseils != null &&
      initialCalcAbseils > 0 &&
      initialData.number_of_abseils !== initialCalcAbseils
  );
  const [isManualLength, setIsManualLength] = useState<boolean>(
    initialData.total_length != null &&
      initialCalcLength > 0 &&
      initialData.total_length !== initialCalcLength
  );

  if (!isEditing && !createMode) {
    const hasData =
      (initialData.number_of_abseils ?? 0) > 0 ||
      (initialData.total_length ?? 0) > 0 ||
      (initialData.pitches && initialData.pitches.length > 0);

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No abseiling details provided.
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

    if (
      initialData.number_of_abseils != null &&
      initialData.number_of_abseils > 0
    ) {
      summaryItems.push({
        label: 'Abseils',
        value: initialData.number_of_abseils,
      });
    }

    if (initialData.total_length != null && initialData.total_length > 0) {
      summaryItems.push({
        label: 'Total Length',
        value: `${initialData.total_length} m`,
      });
    }

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'abseiling-trip-type-editor'}
      >
        <ReadOnlyTypeSummary
          items={summaryItems}
          testId='abseiling-trip-summary'
        />
        <PitchEditor
          pitches={initialData.pitches}
          isEditing={false}
          onChange={() => {}}
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

  const handlePitchesChange = (newPitches: AbseilPitch[]) => {
    setEditData(prev => {
      const newCalcAbseils = newPitches.length;
      const newCalcLength = newPitches.reduce(
        (sum, p) => sum + (p.height || 0),
        0
      );

      let nextAbseils = prev.number_of_abseils;
      if (!isManualAbseils || nextAbseils == null) {
        nextAbseils = newCalcAbseils > 0 ? newCalcAbseils : null;
      }

      let nextLength = prev.total_length;
      if (!isManualLength || nextLength == null) {
        nextLength = newCalcLength > 0 ? newCalcLength : null;
      }

      return {
        ...prev,
        pitches: newPitches,
        number_of_abseils: nextAbseils,
        total_length: nextLength,
      };
    });
  };

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'abseiling-trip-type-editor'}
    >
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        <div className='space-y-2'>
          <Label htmlFor={abseilsFieldId} className='flex items-center gap-2'>
            <Hash
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Number of Abseils
          </Label>
          <Input
            id={abseilsFieldId}
            type='number'
            min={0}
            value={editData.number_of_abseils ?? ''}
            onChange={e => {
              const val = e.target.value;
              setIsManualAbseils(val !== '');
              setEditData(previous => ({
                ...previous,
                number_of_abseils: val === '' ? null : Number.parseInt(val, 10),
              }));
            }}
            data-testid='number-of-abseils-input'
          />
        </div>

        <div className='space-y-2'>
          <Label
            htmlFor={totalLengthFieldId}
            className='flex items-center gap-2'
          >
            <Ruler
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Total Length (m)
          </Label>
          <Input
            id={totalLengthFieldId}
            type='number'
            min={0}
            value={editData.total_length ?? ''}
            onChange={e => {
              const val = e.target.value;
              setIsManualLength(val !== '');
              setEditData(previous => ({
                ...previous,
                total_length: val === '' ? null : Number.parseInt(val, 10),
              }));
            }}
            data-testid='total-length-input'
          />
        </div>
      </div>

      <PitchEditor
        pitches={editData.pitches}
        isEditing={true}
        onChange={handlePitchesChange}
      />

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
