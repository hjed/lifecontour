'use client';

import { useId, useMemo, useState } from 'react';
import { Compass, Hash, Ruler } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { AbseilingData, AbseilPitch } from '@/types/journals';
import {
  ActivityTemplateResource,
  ActivityTemplateType,
} from '@/types/journals';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';
import { PitchEditor } from './PitchEditor';
import { TemplateSelector } from './TemplateSelector';
import { CreateTemplateDialog } from './CreateTemplateDialog';

interface AbseilingTripTypeEditorProps {
  readonly journalId?: string;
  readonly data?: AbseilingData;
  readonly onSave?: (data: AbseilingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: AbseilingData) => void;
  readonly onTemplateSelect?: (
    template: ActivityTemplateResource
  ) => void | Promise<void>;
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
  onTemplateSelect,
}: AbseilingTripTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);
  const baseId = useId();
  const abseilsFieldId = `${baseId}-number-of-abseils`;
  const totalLengthFieldId = `${baseId}-total-length`;
  const templateSelectorId = `${baseId}-template-selector`;

  const [createTemplateOpen, setCreateTemplateOpen] = useState(false);
  const [selectTemplateCreateOpen, setSelectTemplateCreateOpen] =
    useState(false);

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

  const [manualAbseilsState, setManualAbseilsState] = useState<boolean | null>(
    null
  );
  const [manualLengthState, setManualLengthState] = useState<boolean | null>(
    null
  );

  const isManualAbseils =
    manualAbseilsState ??
    (initialData.number_of_abseils != null &&
      initialCalcAbseils > 0 &&
      initialData.number_of_abseils !== initialCalcAbseils);

  const isManualLength =
    manualLengthState ??
    (initialData.total_length != null &&
      initialCalcLength > 0 &&
      initialData.total_length !== initialCalcLength);

  const handleCancelWrapper = () => {
    setManualAbseilsState(null);
    setManualLengthState(null);
    handleCancel();
  };

  const handleSaveWrapper = async () => {
    await handleSave();
    setManualAbseilsState(null);
    setManualLengthState(null);
  };

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
            onSave={handleSaveWrapper}
            onCancel={handleCancelWrapper}
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
          onSave={handleSaveWrapper}
          onCancel={handleCancelWrapper}
        />
      </div>
    );
  }

  const handleTemplateSelection = (template: ActivityTemplateResource) => {
    const pitches = (template.attributes.pitches ?? []) as AbseilPitch[];
    // Persist the durable template reference on the consolidated abseiling block
    // and import the template's standard pitches as editable defaults.
    setEditData(prev => ({
      ...prev,
      template_id: template.id,
      ...(pitches.length > 0
        ? {
            pitches,
            number_of_abseils: pitches.length,
            total_length: pitches.reduce((sum, p) => sum + (p.height || 0), 0),
          }
        : {}),
    }));

    if (onTemplateSelect) {
      Promise.resolve(onTemplateSelect(template)).catch(console.error);
    }
  };

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
      <div className='space-y-2'>
        <Label htmlFor={templateSelectorId} className='flex items-center gap-2'>
          <Compass
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          Template
        </Label>
        <TemplateSelector
          inputId={templateSelectorId}
          templateType={ActivityTemplateType.ABSEILING}
          onSelect={handleTemplateSelection}
          onCreateTemplate={() => setSelectTemplateCreateOpen(true)}
          placeholder='Select an abseiling template...'
        />
        <CreateTemplateDialog
          open={selectTemplateCreateOpen}
          onOpenChange={setSelectTemplateCreateOpen}
          defaultTemplateType={ActivityTemplateType.ABSEILING}
          onCreated={handleTemplateSelection}
        />
      </div>

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
              setManualAbseilsState(val !== '');
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
              setManualLengthState(val !== '');
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

      <div className='mt-4 flex items-center justify-between'>
        <div className='flex-1'>
          {!createMode && (
            <TypeEditorActions
              isEditing={isEditing}
              onEdit={handleEdit}
              onSave={handleSaveWrapper}
              onCancel={handleCancelWrapper}
            />
          )}
        </div>

        {editData.pitches && editData.pitches.length > 0 && (
          <Button
            variant='outline'
            size='sm'
            onClick={() => setCreateTemplateOpen(true)}
            data-testid='save-as-template-button'
            type='button'
          >
            Save Pitches as Template
          </Button>
        )}
      </div>

      <CreateTemplateDialog
        open={createTemplateOpen}
        onOpenChange={setCreateTemplateOpen}
        initialPitches={editData.pitches}
        onCreated={() => setCreateTemplateOpen(false)}
      />
    </div>
  );
}
