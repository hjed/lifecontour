'use client';

import { useId, useMemo } from 'react';
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
      // Auto-calculate totals if there are pitches, and we haven't manually overridden (or if we want to constantly update them unless they have value? The spec says: "Pitch totals auto-calculate from pitches when pitches exist, with manual override")
      // Actually, if we just update the pitches here, the backend might handle auto-calculation.
      // The spec for Phase 2: "Auto-calculation: when pitches present, number_of_abseils defaults to pitch count, total_length to sum of heights, number_of_setups / number_of_rescues to filtered counts. Manual override: user-provided totals take precedence over auto-calculated values."
      // BUT for UI responsiveness, it's nice to auto-update the UI fields if they match the previous auto-calculated values, or if we just let the backend do it?
      // "totals auto-calculate, edit a pitch and verify totals update." -> implies frontend auto-calculation is needed to show the user.

      const previousCalcAbseils = (prev.pitches || []).length;
      const previousCalcLength = (prev.pitches || []).reduce(
        (sum, p) => sum + (p.height || 0),
        0
      );

      const newCalcAbseils = newPitches.length;
      const newCalcLength = newPitches.reduce(
        (sum, p) => sum + (p.height || 0),
        0
      );

      let nextAbseils = prev.number_of_abseils;
      // If the current value was null, or it matched the old calculation, update it.
      if (nextAbseils == null || nextAbseils === previousCalcAbseils) {
        nextAbseils = newCalcAbseils > 0 ? newCalcAbseils : null;
      }

      let nextLength = prev.total_length;
      if (nextLength == null || nextLength === previousCalcLength) {
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
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                number_of_abseils:
                  e.target.value === ''
                    ? null
                    : Number.parseInt(e.target.value, 10),
              }))
            }
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
            onChange={e =>
              setEditData(previous => ({
                ...previous,
                total_length:
                  e.target.value === ''
                    ? null
                    : Number.parseInt(e.target.value, 10),
              }))
            }
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
