'use client';

import { useId, useMemo, useState } from 'react';
import { Compass, Gauge, Moon, Waves } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import type { CanyoningData } from '@/types/journals';
import { buildCanyonFlags, getWaterGaugeLabel } from '../canyoningSummary';
import {
  SummaryBadgeList,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { GenericTypeEditorLayout } from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

import { TemplateSelector } from './TemplateSelector';
import { CreateTemplateDialog } from './CreateTemplateDialog';
import {
  ActivityTemplateResource,
  ActivityTemplateType,
} from '@/types/journals';

interface CanyoningTypeEditorProps {
  readonly journalId?: string;
  readonly data?: CanyoningData;
  readonly onSave?: (data: CanyoningData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: CanyoningData) => void;
  readonly onTemplateSelect?: (template: ActivityTemplateResource) => void;
}

const DEFAULT_DATA: CanyoningData = {};
const FRENCH_GRADE_PATTERN = /^v([1-7])a([1-7])(VI|IV|V|III|II|I)(\*{0,3})$/i;
const FRENCH_GRADE_ERROR = 'Use format v3a2IV**';

interface GradeState {
  readonly resetKey: string;
  readonly input: string;
  readonly error: string | null;
}

function normalizeFrenchCanyonGrade(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === '') return null;

  const match = FRENCH_GRADE_PATTERN.exec(trimmed);
  if (!match) return null;

  const [, vertical, aquatic, engagement, stars] = match;
  return `v${vertical}a${aquatic}${engagement.toUpperCase()}${stars}`;
}

function createSavedGradeState(
  resetKey: string,
  frenchGrade: string | null | undefined
): GradeState {
  return {
    resetKey,
    input: frenchGrade ?? '',
    error: null,
  };
}

function createTransientGradeState(
  resetKey: string,
  input: string,
  error: string | null = null
): GradeState {
  return {
    resetKey,
    input,
    error,
  };
}

function buildReadOnlySummaryItems(
  data: CanyoningData,
  canyonFlags: string[]
): ReadOnlyTypeSummaryItem[] {
  const waterGaugeSummary = getWaterGaugeLabel(data);
  const summaryItems: ReadOnlyTypeSummaryItem[] = [];

  if (data.french_grade) {
    summaryItems.push({
      label: 'French Grade',
      value: data.french_grade,
    });
  }

  if (waterGaugeSummary) {
    summaryItems.push({
      label: 'Water Gauge',
      value: waterGaugeSummary,
    });
  }

  if (canyonFlags.length > 0) {
    summaryItems.push({
      label: 'Flags',
      value: <SummaryBadgeList values={canyonFlags} />,
      fullWidth: true,
    });
  }

  return summaryItems;
}

export function CanyoningTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
  onTemplateSelect,
}: CanyoningTypeEditorProps) {
  const baseId = useId();
  const frenchGradeFieldId = `${baseId}-french-grade`;
  const waterGaugeNameFieldId = `${baseId}-water-gauge-name`;
  const waterGaugeLevelFieldId = `${baseId}-water-gauge-level`;
  const verticalFieldId = `${baseId}-vertical`;
  const nightCanyonFieldId = `${baseId}-night-canyon`;
  const whiteWaterFieldId = `${baseId}-white-water`;

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

  const gradeResetKey = useMemo(
    () => JSON.stringify(data ?? DEFAULT_DATA),
    [data]
  );
  const [gradeState, setGradeState] = useState<GradeState>(() =>
    createSavedGradeState(gradeResetKey, data?.french_grade)
  );
  const currentGradeState =
    gradeState.resetKey === gradeResetKey
      ? gradeState
      : createSavedGradeState(gradeResetKey, data?.french_grade);

  const canyonFlags = buildCanyonFlags(data ?? DEFAULT_DATA);

  const handleFrenchGradeChange = (value: string) => {
    const nextGradeState = createTransientGradeState(gradeResetKey, value);

    if (value.trim() === '') {
      setGradeState(nextGradeState);
      setEditData(previous => ({ ...previous, french_grade: null }));
      return;
    }

    const normalized = normalizeFrenchCanyonGrade(value);
    if (normalized) {
      setGradeState(nextGradeState);
      setEditData(previous => ({ ...previous, french_grade: normalized }));
      return;
    }

    setGradeState(
      createTransientGradeState(gradeResetKey, value, FRENCH_GRADE_ERROR)
    );
    setEditData(previous => ({ ...previous, french_grade: null }));
  };

  const handleEditorCancel = () => {
    setGradeState(createSavedGradeState(gradeResetKey, data?.french_grade));
    handleCancel();
  };

  const summaryItems = buildReadOnlySummaryItems(
    data ?? DEFAULT_DATA,
    canyonFlags
  );

  const [createTemplateOpen, setCreateTemplateOpen] = useState(false);

  const handleTemplateSelection = (template: ActivityTemplateResource) => {
    // Update local canyoning data fields that the template provides
    setEditData(prev => {
      const next = {
        ...prev,
        template_id: template.id,
      };
      if (template.attributes.french_grade) {
        next.french_grade = template.attributes.french_grade;
        setGradeState(
          createTransientGradeState(
            gradeResetKey,
            template.attributes.french_grade
          )
        );
      }
      if (template.attributes.water_gauge_name) {
        next.water_guage_name = template.attributes.water_gauge_name;
      }
      if (template.attributes.is_vertical != null) {
        next.is_vertical = template.attributes.is_vertical;
      }
      return next;
    });

    if (onTemplateSelect) {
      onTemplateSelect(template);
    }
  };

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'canyoning-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='No canyoning details provided.'
      summaryItems={summaryItems}
      summaryTestId='canyoning-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleEditorCancel}
    >
      <div className='space-y-2'>
        <Label htmlFor='template-selector' className='flex items-center gap-2'>
          <Compass
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          Template
        </Label>
        <TemplateSelector
          inputId='template-selector'
          templateType={ActivityTemplateType.CANYONING}
          onSelect={handleTemplateSelection}
          onCreateTemplate={() => setCreateTemplateOpen(true)}
          disabled={!isEditing && !createMode}
          placeholder='Select a canyoning template...'
        />
        <CreateTemplateDialog
          open={createTemplateOpen}
          onOpenChange={setCreateTemplateOpen}
          templateType={ActivityTemplateType.CANYONING}
          onCreated={handleTemplateSelection}
        />
      </div>

      <div className='space-y-2'>
        <Label htmlFor={frenchGradeFieldId} className='flex items-center gap-2'>
          <Compass
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          French Grade
        </Label>
        <Input
          id={frenchGradeFieldId}
          type='text'
          value={currentGradeState.input}
          onChange={e => handleFrenchGradeChange(e.target.value)}
          placeholder='e.g. v3a2IV**'
          aria-invalid={currentGradeState.error ? true : undefined}
          data-testid='french-grade-input'
        />
        {currentGradeState.error && (
          <p className='text-destructive text-sm'>{currentGradeState.error}</p>
        )}
      </div>

      <div className='space-y-2'>
        <Label
          htmlFor={waterGaugeNameFieldId}
          className='flex items-center gap-2'
        >
          <Gauge className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          Water Gauge Name
        </Label>
        <Input
          id={waterGaugeNameFieldId}
          type='text'
          value={editData.water_guage_name ?? ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              water_guage_name: e.target.value || null,
            }))
          }
          placeholder='e.g. Kowmung Gauge'
          data-testid='water-gauge-name-input'
        />
      </div>

      <div className='space-y-2'>
        <Label
          htmlFor={waterGaugeLevelFieldId}
          className='flex items-center gap-2'
        >
          <Gauge className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          Water Gauge Level
        </Label>
        <Input
          id={waterGaugeLevelFieldId}
          type='number'
          value={editData.water_guage_level ?? ''}
          onChange={e =>
            setEditData(previous => ({
              ...previous,
              water_guage_level:
                e.target.value === ''
                  ? null
                  : Number.parseInt(e.target.value, 10),
            }))
          }
          data-testid='water-gauge-level-input'
        />
      </div>

      <div className='flex items-center space-x-2 pt-2'>
        <Switch
          id={verticalFieldId}
          checked={editData.is_vertical ?? false}
          onCheckedChange={(checked: boolean) =>
            setEditData(previous => ({ ...previous, is_vertical: checked }))
          }
          data-testid='vertical-switch'
        />
        <Label htmlFor={verticalFieldId}>Vertical</Label>
      </div>

      <div className='flex items-center space-x-2 pt-2'>
        <Switch
          id={nightCanyonFieldId}
          checked={editData.is_night_canyon ?? false}
          onCheckedChange={(checked: boolean) =>
            setEditData(previous => ({
              ...previous,
              is_night_canyon: checked,
            }))
          }
          data-testid='night-canyon-switch'
        />
        <Label htmlFor={nightCanyonFieldId} className='flex items-center gap-2'>
          <Moon className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          Night Canyon
        </Label>
      </div>

      <div className='flex items-center space-x-2 pt-2'>
        <Switch
          id={whiteWaterFieldId}
          checked={editData.is_white_water ?? false}
          onCheckedChange={(checked: boolean) =>
            setEditData(previous => ({
              ...previous,
              is_white_water: checked,
            }))
          }
          data-testid='white-water-switch'
        />
        <Label htmlFor={whiteWaterFieldId} className='flex items-center gap-2'>
          <Waves className='text-muted-foreground h-4 w-4' aria-hidden='true' />
          White Water
        </Label>
      </div>
    </GenericTypeEditorLayout>
  );
}
