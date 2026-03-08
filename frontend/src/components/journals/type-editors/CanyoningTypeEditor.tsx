'use client';

import { useId, useMemo, useState } from 'react';
import { Compass, Gauge, Map as MapIcon, Moon, Waves } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import type { CanyoningData } from '@/types/journals';
import { RouteSelector } from '@/components/routes/RouteSelector';
import { useRoute } from '@/lib/api/routes';
import {
  ReadOnlyTypeSummary,
  SummaryBadgeList,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { useTypeEditorState } from './useTypeEditorState';
import { TypeEditorActions } from './TypeEditorActions';

interface CanyoningTypeEditorProps {
  readonly journalId?: string;
  readonly data?: CanyoningData;
  readonly onSave?: (data: CanyoningData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: CanyoningData) => void;
}

const DEFAULT_DATA: CanyoningData = {};
const FRENCH_GRADE_PATTERN = /^v([1-7])a([1-7])(VI|IV|V|III|II|I)(\*{0,3})$/i;

function normalizeFrenchCanyonGrade(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === '') return null;

  const match = trimmed.match(FRENCH_GRADE_PATTERN);
  if (!match) return null;

  const [, vertical, aquatic, engagement, stars] = match;
  return `v${vertical}a${aquatic}${engagement.toUpperCase()}${stars}`;
}

export function CanyoningTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: CanyoningTypeEditorProps) {
  const initialData = useMemo(() => data ?? DEFAULT_DATA, [data]);
  const { data: routeData } = useRoute(initialData.route_id ?? '');
  const routeName = routeData?.data?.attributes?.name;
  const baseId = useId();
  const routeFieldId = `${baseId}-route`;
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
    initialData,
    onSave,
    createMode,
    onChange,
  });

  const [gradeInput, setGradeInput] = useState(initialData.french_grade ?? '');
  const [gradeError, setGradeError] = useState<string | null>(null);

  const canyonFlags = [
    initialData.is_vertical ? 'Vertical' : null,
    initialData.is_night_canyon ? 'Night Canyon' : null,
    initialData.is_white_water ? 'White Water' : null,
  ].filter((flag): flag is string => flag !== null);

  const handleFrenchGradeChange = (value: string) => {
    setGradeInput(value);

    if (value.trim() === '') {
      setGradeError(null);
      setEditData({ ...editData, french_grade: null });
      return;
    }

    const normalized = normalizeFrenchCanyonGrade(value);
    if (normalized) {
      setGradeError(null);
      setEditData({ ...editData, french_grade: normalized });
      return;
    }

    setGradeError('Use format v3a2IV**');
  };

  if (!isEditing && !createMode) {
    const hasData =
      initialData.route_id ||
      initialData.french_grade ||
      initialData.water_guage_name ||
      initialData.water_guage_level != null ||
      canyonFlags.length > 0;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No canyoning details provided.
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

    if (initialData.route_id) {
      summaryItems.push({
        label: 'Route',
        value: routeName ?? initialData.route_id,
      });
    }

    if (initialData.french_grade) {
      summaryItems.push({
        label: 'French Grade',
        value: initialData.french_grade,
      });
    }

    if (initialData.water_guage_name || initialData.water_guage_level != null) {
      summaryItems.push({
        label: 'Water Gauge',
        value: `${initialData.water_guage_name ?? 'Gauge'}${
          initialData.water_guage_level != null
            ? ` (${initialData.water_guage_level})`
            : ''
        }`,
      });
    }

    if (canyonFlags.length > 0) {
      summaryItems.push({
        label: 'Flags',
        value: <SummaryBadgeList values={canyonFlags} />,
        fullWidth: true,
      });
    }

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'canyoning-type-editor'}
      >
        <ReadOnlyTypeSummary items={summaryItems} testId='canyoning-summary' />
        <TypeEditorActions
          isEditing={false}
          onEdit={handleEdit}
          onSave={handleSave}
          onCancel={handleCancel}
        />
      </div>
    );
  }

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'canyoning-type-editor'}
    >
      <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
        <div className='space-y-2'>
          <Label htmlFor={routeFieldId} className='flex items-center gap-2'>
            <MapIcon
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Route
          </Label>
          <RouteSelector
            id={routeFieldId}
            value={editData.route_id ?? null}
            onChange={routeId =>
              setEditData({ ...editData, route_id: routeId })
            }
            placeholder='Select a canyon route...'
          />
        </div>

        <div className='space-y-2'>
          <Label
            htmlFor={frenchGradeFieldId}
            className='flex items-center gap-2'
          >
            <Compass
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            French Grade
          </Label>
          <Input
            id={frenchGradeFieldId}
            type='text'
            value={gradeInput}
            onChange={e => handleFrenchGradeChange(e.target.value)}
            placeholder='e.g. v3a2IV**'
            aria-invalid={gradeError ? true : undefined}
            data-testid='french-grade-input'
          />
          {gradeError && (
            <p className='text-destructive text-sm'>{gradeError}</p>
          )}
        </div>

        <div className='space-y-2'>
          <Label
            htmlFor={waterGaugeNameFieldId}
            className='flex items-center gap-2'
          >
            <Gauge
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Water Gauge Name
          </Label>
          <Input
            id={waterGaugeNameFieldId}
            type='text'
            value={editData.water_guage_name ?? ''}
            onChange={e =>
              setEditData({
                ...editData,
                water_guage_name: e.target.value || null,
              })
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
            <Gauge
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Water Gauge Level
          </Label>
          <Input
            id={waterGaugeLevelFieldId}
            type='number'
            value={editData.water_guage_level ?? ''}
            onChange={e =>
              setEditData({
                ...editData,
                water_guage_level:
                  e.target.value === ''
                    ? null
                    : Number.parseInt(e.target.value, 10),
              })
            }
            data-testid='water-gauge-level-input'
          />
        </div>

        <div className='flex items-center space-x-2 pt-2'>
          <Switch
            id={verticalFieldId}
            checked={editData.is_vertical ?? false}
            onCheckedChange={(checked: boolean) =>
              setEditData({ ...editData, is_vertical: checked })
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
              setEditData({ ...editData, is_night_canyon: checked })
            }
            data-testid='night-canyon-switch'
          />
          <Label
            htmlFor={nightCanyonFieldId}
            className='flex items-center gap-2'
          >
            <Moon
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Night Canyon
          </Label>
        </div>

        <div className='flex items-center space-x-2 pt-2'>
          <Switch
            id={whiteWaterFieldId}
            checked={editData.is_white_water ?? false}
            onCheckedChange={(checked: boolean) =>
              setEditData({ ...editData, is_white_water: checked })
            }
            data-testid='white-water-switch'
          />
          <Label
            htmlFor={whiteWaterFieldId}
            className='flex items-center gap-2'
          >
            <Waves
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            White Water
          </Label>
        </div>
      </div>

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
