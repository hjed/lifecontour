/**
 * Form component for creating a new journal entry.
 *
 * Provides fields for title, date range, content, and type selection.
 * Shows inline type editors for selected types (in create mode).
 * Handles validation and submission via the journals API.
 */

'use client';

import { useCallback, useRef, useState } from 'react';

/**
 * Format a Date as a local YYYY-MM-DD string for HTML date inputs.
 * Unlike toISOString().split('T')[0], this avoids UTC conversion
 * which can shift the date across timezone boundaries.
 */
function formatLocalDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Parse a YYYY-MM-DD string into a local Date at midnight.
 * Using `new Date('YYYY-MM-DD')` parses as UTC; this parses as local time.
 */
function parseLocalDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, d);
}
import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import {
  useForm,
  useWatch,
  type Control,
  type UseFormSetError,
} from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MarkdownEditor } from '@/components/journals/MarkdownEditor';
import { Checkbox } from '@/components/ui/checkbox';
import { useCreateJournal, useJournal } from '@/lib/api/journals';
import { zonedMidnight } from '@/lib/date-utils';
import { journalTimezone, useUserTimezone } from '@/lib/api/settings';
import { useCreateRoute } from '@/lib/api/routes';
import { toast } from 'sonner';
import {
  JournalType,
  type AbseilingData,
  type CanyoningData,
  type CavingData,
  type CanoeingData,
  type ClimbingData,
  type CrossCountrySkiingData,
  type CalendarInfoData,
  type JournalTypeData,
  type KayakingData,
  type MoodData,
  type PlanData,
  type TravelData,
  type FitnessData,
  type OutdoorActivityData,
  type JoggingData,
  type BushwalkingData,
  type OutdoorPlanningData,
  OutdoorTrainingData,
  type GearMaintenanceData,
  ActivityTemplateResource,
  AbseilPitch,
  GearUsageData,
} from '@/types/journals';
import {
  AbseilingTripTypeEditor,
  BushwalkingTypeEditor,
  CanyoningTypeEditor,
  CavingTypeEditor,
  CanoeingTypeEditor,
  ClimbingTypeEditor,
  CrossCountrySkiingTypeEditor,
  EventTypeEditor,
  FitnessTypeEditor,
  JoggingTypeEditor,
  KayakingTypeEditor,
  MoodRatingTypeEditor,
  OutdoorActivityTypeEditor,
  PlanTypeEditor,
  TravelTypeEditor,
  SnorkellingTypeEditor,
  DivingTypeEditor,
  DownhillSkiingTypeEditor,
  OutdoorPlanningTypeEditor,
  OutdoorTrainingTypeEditor,
  GearMaintenanceTypeEditor,
  GearUsageTypeEditor,
} from './type-editors';
import {
  gearUsageItems,
  gearUsageItemsError,
} from './type-editors/gearUsageItems';
import { countAbseils } from './type-editors/pitchUtils';
import {
  templateTypeFieldUpdates,
  templateTypesForJournalTypes,
} from './templateUtils';
import { JournalSearchCombobox } from './JournalSearchCombobox';

// Form validation schema
const formSchema = z.object({
  title: z.string().min(1, 'Title is required'),
  dateRange: z
    .object({
      from: z.date(),
      to: z.date().optional(),
    })
    .refine(data => !data.to || data.to >= data.from, {
      message: 'End date cannot be before start date',
      path: ['to'],
    }),
  content: z.string(),
  types: z.array(z.nativeEnum(JournalType)),
  parentId: z.number().nullable().optional(),
});

type FormValues = z.infer<typeof formSchema>;

// Type-specific data collected from inline editors
interface TypeDataState {
  [JournalType.EVENT]?: CalendarInfoData;
  [JournalType.MOOD_RATING]?: MoodData;
  [JournalType.PLAN]?: PlanData;
  [JournalType.TRAVEL]?: TravelData;
  [JournalType.FITNESS]?: FitnessData;
  [JournalType.OUTDOOR_ACTIVITY]?: OutdoorActivityData;
  [JournalType.JOGGING]?: JoggingData;
  [JournalType.BUSHWALKING]?: BushwalkingData;
  [JournalType.ABSEILING_TRIP]?: AbseilingData;
  [JournalType.CANYONING]?: CanyoningData;
  [JournalType.CAVING]?: CavingData;
  [JournalType.CANOEING]?: CanoeingData;
  [JournalType.CLIMBING]?: ClimbingData;
  [JournalType.KAYAKING]?: KayakingData;
  [JournalType.CROSS_COUNTRY_SKIING]?: CrossCountrySkiingData;
  [JournalType.SNORKELLING]?: Record<string, never>;
  [JournalType.DIVING]?: Record<string, never>;
  [JournalType.DOWNHILL_SKIING]?: Record<string, never>;
  [JournalType.OUTDOOR_PLANNING]?: OutdoorPlanningData;
  [JournalType.OUTDOOR_TRAINING]?: OutdoorTrainingData;
  [JournalType.GEAR_MAINTENANCE]?: GearMaintenanceData;
  [JournalType.GEAR_USAGE]?: GearUsageData;
}

type TypeDataJournalType = keyof TypeDataState;

const TYPE_DATA_JOURNAL_TYPES = new Set<TypeDataJournalType>([
  JournalType.EVENT,
  JournalType.MOOD_RATING,
  JournalType.PLAN,
  JournalType.TRAVEL,
  JournalType.FITNESS,
  JournalType.OUTDOOR_ACTIVITY,
  JournalType.JOGGING,
  JournalType.BUSHWALKING,
  JournalType.ABSEILING_TRIP,
  JournalType.CANYONING,
  JournalType.CAVING,
  JournalType.CANOEING,
  JournalType.CLIMBING,
  JournalType.KAYAKING,
  JournalType.CROSS_COUNTRY_SKIING,
  JournalType.SNORKELLING,
  JournalType.DIVING,
  JournalType.DOWNHILL_SKIING,
  JournalType.OUTDOOR_PLANNING,
  JournalType.GEAR_MAINTENANCE,
  JournalType.GEAR_USAGE,
]);

function hasTypeDataJournalType(
  type: JournalType
): type is TypeDataJournalType {
  return TYPE_DATA_JOURNAL_TYPES.has(type as TypeDataJournalType);
}

// User-creatable journal type checkboxes. Should list every `JournalType`
// except PHOTO_ALBUM, which is created only by Immich album sync (see
// CreateAlbumButton). Keep in sync with the JournalType enum — the
// "offers every creatable journal type" test in JournalCreateForm.test.tsx
// guards against a type being forgotten here.
const typeOptions = [
  { value: JournalType.NOTE, label: 'Note' },
  { value: JournalType.EVENT, label: 'Event' },
  { value: JournalType.MOOD_RATING, label: 'Mood Rating' },
  { value: JournalType.PLAN, label: 'Plan' },
  { value: JournalType.TRAVEL, label: 'Travel' },
  { value: JournalType.FITNESS, label: 'Fitness' },
  { value: JournalType.OUTDOOR_ACTIVITY, label: 'Outdoor Activity' },
  { value: JournalType.BUSHWALKING, label: 'Bushwalking' },
  { value: JournalType.JOGGING, label: 'Jogging' },
  { value: JournalType.ABSEILING_TRIP, label: 'Abseiling Trip' },
  { value: JournalType.CANYONING, label: 'Canyoning' },
  { value: JournalType.CAVING, label: 'Caving' },
  { value: JournalType.CANOEING, label: 'Canoeing' },
  { value: JournalType.CLIMBING, label: 'Climbing' },
  { value: JournalType.KAYAKING, label: 'Kayaking' },
  { value: JournalType.CROSS_COUNTRY_SKIING, label: 'Cross-Country Skiing' },
  { value: JournalType.SNORKELLING, label: 'Snorkelling' },
  { value: JournalType.DIVING, label: 'Diving' },
  { value: JournalType.DOWNHILL_SKIING, label: 'Downhill Skiing' },
  { value: JournalType.OUTDOOR_PLANNING, label: 'Outdoor Planning' },
  { value: JournalType.OUTDOOR_TRAINING, label: 'Outdoor Training' },
  { value: JournalType.GEAR_MAINTENANCE, label: 'Gear Maintenance' },
  { value: JournalType.GEAR_USAGE, label: 'Gear Usage' },
];

/**
 * Types that have dependencies automatically added by the backend.
 * Mirrors the dependency map in backend/app/core/journal/models/journal_types.py.
 */
const TYPE_DEPENDENCIES: Partial<Record<JournalType, JournalType[]>> = {
  [JournalType.OUTDOOR_ACTIVITY]: [JournalType.FITNESS],
  [JournalType.BUSHWALKING]: [
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.JOGGING]: [JournalType.FITNESS],
  [JournalType.ABSEILING_TRIP]: [
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.CANYONING]: [
    JournalType.BUSHWALKING,
    JournalType.ABSEILING_TRIP,
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.CLIMBING]: [
    JournalType.ABSEILING_TRIP,
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.KAYAKING]: [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS],
  [JournalType.CROSS_COUNTRY_SKIING]: [
    JournalType.BUSHWALKING,
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.CAVING]: [
    JournalType.ABSEILING_TRIP,
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.CANOEING]: [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS],
  [JournalType.SNORKELLING]: [
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
  [JournalType.DIVING]: [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS],
  [JournalType.DOWNHILL_SKIING]: [
    JournalType.OUTDOOR_ACTIVITY,
    JournalType.FITNESS,
  ],
};

interface TypeCheckboxFieldProps {
  readonly control: Control<FormValues>;
  readonly option: { readonly value: JournalType; readonly label: string };
}

/**
 * Individual checkbox field for a journal type option.
 * Extracted to a module-level component to keep function nesting within limits.
 */
function TypeCheckboxField({ control, option }: TypeCheckboxFieldProps) {
  return (
    <FormField
      control={control}
      name='types'
      render={({ field }) => (
        <FormItem className='flex flex-row items-start space-y-0 space-x-3'>
          <FormControl>
            <Checkbox
              checked={field.value?.includes(option.value)}
              onCheckedChange={checked => {
                let newValue: JournalType[];
                if (checked) {
                  const deps = TYPE_DEPENDENCIES[option.value] || [];
                  newValue = Array.from(
                    new Set([...(field.value || []), option.value, ...deps])
                  );
                } else {
                  // Determine base remaining items
                  let remaining = (field.value || []).filter(
                    v => v !== option.value
                  );

                  // Re-evaluate what dependencies should be kept by checking the remaining types
                  const depsToRemove = TYPE_DEPENDENCIES[option.value] || [];
                  if (depsToRemove.length > 0) {
                    const otherDeps = new Set<JournalType>();
                    for (const type of remaining) {
                      const deps = TYPE_DEPENDENCIES[type] || [];
                      deps.forEach(d => otherDeps.add(d));
                    }
                    // Remove dependency if no other remaining type needs it
                    // NOTE: This treats explicitly selected dependencies as implicit ones
                    // and removes them if the parent is unchecked.
                    remaining = remaining.filter(
                      type =>
                        !depsToRemove.includes(type) || otherDeps.has(type)
                    );
                  }

                  newValue = remaining;
                }
                field.onChange(newValue);
              }}
            />
          </FormControl>
          <FormLabel className='font-normal'>{option.label}</FormLabel>
        </FormItem>
      )}
    />
  );
}

/** Human-readable labels for displaying dependency names to users. */
export const TYPE_LABELS: Record<JournalType, string> = {
  [JournalType.NOTE]: 'Note',
  [JournalType.EVENT]: 'Event',
  [JournalType.MOOD_RATING]: 'Mood Rating',
  [JournalType.PLAN]: 'Plan',
  [JournalType.TRAVEL]: 'Travel',
  [JournalType.PHOTO_ALBUM]: 'Photo Album',
  [JournalType.FITNESS]: 'Fitness',
  [JournalType.OUTDOOR_ACTIVITY]: 'Outdoor Activity',
  [JournalType.BUSHWALKING]: 'Bushwalking',
  [JournalType.JOGGING]: 'Jogging',
  [JournalType.ABSEILING_TRIP]: 'Abseiling Trip',
  [JournalType.CANYONING]: 'Canyoning',
  [JournalType.CAVING]: 'Caving',
  [JournalType.CANOEING]: 'Canoeing',
  [JournalType.CLIMBING]: 'Climbing',
  [JournalType.KAYAKING]: 'Kayaking',
  [JournalType.CROSS_COUNTRY_SKIING]: 'Cross-Country Skiing',
  [JournalType.SNORKELLING]: 'Snorkelling',
  [JournalType.DIVING]: 'Diving',
  [JournalType.DOWNHILL_SKIING]: 'Downhill Skiing',
  [JournalType.OUTDOOR_PLANNING]: 'Outdoor Planning',
  [JournalType.OUTDOOR_TRAINING]: 'Outdoor Training',
  [JournalType.GEAR_MAINTENANCE]: 'Gear Maintenance',
  [JournalType.GEAR_USAGE]: 'Gear Usage',
};

function getJournalTypeTestId(type: JournalType): string {
  return type.toUpperCase();
}

type SelectedTypeData = TypeDataState[keyof TypeDataState];

function setTypesError(
  setError: UseFormSetError<FormValues>,
  message: string
): void {
  setError('types', {
    type: 'manual',
    message,
  });
}

function hasRequiredTypeData(
  type: JournalType,
  data: SelectedTypeData,
  setError: UseFormSetError<FormValues>
): boolean {
  if (type === JournalType.EVENT) {
    const eventData = data as CalendarInfoData | undefined;
    if (!eventData?.calendar_id?.trim()) {
      setTypesError(setError, 'Event requires a valid Calendar ID.');
      return false;
    }
  }

  if (type === JournalType.GEAR_USAGE) {
    const error = gearUsageItemsError(
      gearUsageItems(data as GearUsageData | undefined)
    );
    if (error) {
      setTypesError(setError, error);
      return false;
    }
  }

  return true;
}

function sanitiseTypeData(
  type: JournalType,
  data: Exclude<SelectedTypeData, undefined>
): JournalTypeData {
  if (type === JournalType.PLAN) {
    const planData = data as PlanData;
    return {
      ...planData,
      documents: planData.documents.filter(
        doc => doc.url && doc.url.trim() !== ''
      ),
    };
  }

  return data;
}

function buildSubmittedTypeData(
  selectedTypes: readonly JournalType[],
  typeData: TypeDataState,
  setError: UseFormSetError<FormValues>
): Record<string, JournalTypeData> | null {
  const submittedTypeData: Record<string, JournalTypeData> = {};

  for (const type of selectedTypes) {
    const currentTypeData = hasTypeDataJournalType(type)
      ? typeData[type]
      : undefined;

    if (!hasRequiredTypeData(type, currentTypeData, setError)) {
      return null;
    }

    if (currentTypeData === undefined) {
      continue;
    }

    submittedTypeData[type] = sanitiseTypeData(type, currentTypeData);
  }

  return submittedTypeData;
}

interface JournalCreateFormProps {
  readonly onCancel?: () => void;
  readonly onSuccess?: (journalId: string) => void;
  readonly defaultParentId?: number;
  readonly initialDate?: { from: Date; to?: Date };
  readonly initialTypes?: JournalType[];
}

export function JournalCreateForm({
  onCancel,
  onSuccess,
  defaultParentId,
  initialDate,
  initialTypes,
}: JournalCreateFormProps = {}) {
  const router = useRouter();
  const { mutateAsync: createJournal, isPending: isCreatingJournal } =
    useCreateJournal();
  const { mutateAsync: createRoute, isPending: isCreatingRoute } =
    useCreateRoute();
  /** The user's own zone, the fallback when the journal records none. */
  const userTimezone = useUserTimezone();
  const [typeData, setTypeData] = useState<TypeDataState>({});
  const [abseilKey, setAbseilKey] = useState(0);
  // Snapshot of type-specific values applied from a template. Passed as the
  // editors' `data` (with `key={abseilKey}` forcing a remount on template
  // apply) so template fields render without feeding live edits back into the
  // editors' internal state.
  const [templateSeedData, setTemplateSeedData] = useState<TypeDataState>({});

  // Fetch parent journal title for pre-population
  const { data: parentJournalData } = useJournal(
    defaultParentId ? String(defaultParentId) : ''
  );
  const defaultParentTitle = parentJournalData?.data?.attributes?.title ?? '';
  // Track whether user has manually changed the parent selector,
  // preventing the async title fetch from overwriting their selection
  const parentUserModified = useRef(false);

  const isPending = isCreatingJournal || isCreatingRoute;

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      title: '',
      dateRange: initialDate || {
        from: new Date(),
        to: undefined,
      },
      content: '',
      types: initialTypes || [],
      parentId: defaultParentId ?? undefined,
    },
  });

  const selectedTypes =
    useWatch({
      control: form.control,
      name: 'types',
    }) || [];

  const handleTypeDataChange = useCallback(
    <K extends keyof TypeDataState>(type: K, data: TypeDataState[K]) => {
      setTypeData(prev => ({ ...prev, [type]: data }));
    },
    []
  );

  const handleEventChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.EVENT, data as CalendarInfoData),
    [handleTypeDataChange]
  );

  const handleMoodRatingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.MOOD_RATING, data as MoodData),
    [handleTypeDataChange]
  );

  const handlePlanChange = useCallback(
    (data: unknown) => handleTypeDataChange(JournalType.PLAN, data as PlanData),
    [handleTypeDataChange]
  );

  const handleTravelChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.TRAVEL, data as TravelData),
    [handleTypeDataChange]
  );

  const handleFitnessChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.FITNESS, data as FitnessData),
    [handleTypeDataChange]
  );

  const handleOutdoorActivityChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.OUTDOOR_ACTIVITY,
        data as OutdoorActivityData
      ),
    [handleTypeDataChange]
  );

  const handleJoggingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.JOGGING, data as JoggingData),
    [handleTypeDataChange]
  );

  const handleBushwalkingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.BUSHWALKING, data as BushwalkingData),
    [handleTypeDataChange]
  );

  const handleAbseilingTripChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.ABSEILING_TRIP, data as AbseilingData),
    [handleTypeDataChange]
  );

  const handleCanyoningChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.CANYONING, data as CanyoningData),
    [handleTypeDataChange]
  );

  const handleCavingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.CAVING, data as CavingData),
    [handleTypeDataChange]
  );

  const handleCanoeingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.CANOEING, data as CanoeingData),
    [handleTypeDataChange]
  );

  const handleTemplateSelect = useCallback(
    (template: ActivityTemplateResource) => {
      // A canyoning/caving/climbing template also contributes its
      // type-specific fields (grade, gauge, style, …) to the matching type
      // block; unselected types are dropped at submission.
      const typeFieldUpdates = templateTypeFieldUpdates(template);

      setTypeData(prev => {
        const pitches = (template.attributes.pitches || []) as AbseilPitch[];
        const hasPitches = pitches.length > 0;

        return {
          ...prev,
          ...(typeFieldUpdates
            ? {
                [typeFieldUpdates.journalType]: {
                  ...(prev[typeFieldUpdates.journalType] || {}),
                  ...typeFieldUpdates.fields,
                },
              }
            : {}),
          [JournalType.ABSEILING_TRIP]: {
            ...(prev[JournalType.ABSEILING_TRIP] || {}),
            // Durable template reference lives on the consolidated abseiling
            // block for all abseiling-derived journals (ITER16-001). Only import
            // the template's standard pitches when it has some — linking a
            // pitch-less template must not clear user-entered abseil data.
            template_id: template.id,
            ...(hasPitches
              ? {
                  pitches,
                  number_of_abseils: countAbseils(pitches),
                  total_length: pitches.reduce(
                    (sum, p) => sum + (p.height || 0),
                    0
                  ),
                }
              : {}),
          },
        };
      });
      // Every template selection remounts the subtype editors (via
      // abseilKey), and a remounted editor re-emits its seed to the parent
      // form — so the seed must snapshot the user's current values for every
      // derived block on every selection, with the template's own fields
      // overlaid where applicable. Seeding only the template's block would
      // wipe user-entered fields in the others.
      setTemplateSeedData({
        [JournalType.CANYONING]: typeData[JournalType.CANYONING],
        [JournalType.CAVING]: typeData[JournalType.CAVING],
        [JournalType.CLIMBING]: typeData[JournalType.CLIMBING],
        ...(typeFieldUpdates
          ? {
              [typeFieldUpdates.journalType]: {
                ...(typeData[typeFieldUpdates.journalType] || {}),
                ...typeFieldUpdates.fields,
              },
            }
          : {}),
      });
      setAbseilKey(k => k + 1);

      if (
        template.attributes.pitches &&
        template.attributes.pitches.length > 0
      ) {
        toast.success('Pitches imported from template');
      }
    },
    [typeData]
  );

  const handleClimbingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.CLIMBING, data as ClimbingData),
    [handleTypeDataChange]
  );

  const handleKayakingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.KAYAKING, data as KayakingData),
    [handleTypeDataChange]
  );

  const handleCrossCountrySkiingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.CROSS_COUNTRY_SKIING,
        data as CrossCountrySkiingData
      ),
    [handleTypeDataChange]
  );

  const handleSnorkellingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.SNORKELLING,
        data as Record<string, never>
      ),
    [handleTypeDataChange]
  );

  const handleDivingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.DIVING, data as Record<string, never>),
    [handleTypeDataChange]
  );

  const handleDownhillSkiingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.DOWNHILL_SKIING,
        data as Record<string, never>
      ),
    [handleTypeDataChange]
  );

  const handleOutdoorPlanningChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.OUTDOOR_PLANNING,
        data as OutdoorPlanningData
      ),
    [handleTypeDataChange]
  );

  const handleOutdoorTrainingChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.OUTDOOR_TRAINING,
        data as OutdoorTrainingData
      ),
    [handleTypeDataChange]
  );

  const handleGearMaintenanceChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(
        JournalType.GEAR_MAINTENANCE,
        data as GearMaintenanceData
      ),
    [handleTypeDataChange]
  );

  const handleGearUsageChange = useCallback(
    (data: unknown) =>
      handleTypeDataChange(JournalType.GEAR_USAGE, data as GearUsageData),
    [handleTypeDataChange]
  );

  const onSubmit = async (values: FormValues) => {
    try {
      const endDate = values.dateRange.to || values.dateRange.from;

      const submittedTypeData = buildSubmittedTypeData(
        values.types,
        typeData,
        form.setError
      );

      if (submittedTypeData === null) {
        return;
      }

      const rangeTimezone = journalTimezone(
        (submittedTypeData[JournalType.EVENT] as CalendarInfoData | undefined)
          ?.timezone,
        userTimezone
      );

      // Extract pending routes to upload them separately since backend doesn't accept them in JournalCreateData
      let pendingRoutes: { name: string; gpx_data: string }[] = [];
      const fitnessData = submittedTypeData[JournalType.FITNESS] as
        FitnessData | undefined;
      if (fitnessData?.pending_routes) {
        pendingRoutes = [...fitnessData.pending_routes];
        // Remove pending_routes before submitting to prevent validation errors
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { pending_routes, ...sanitizedFitnessData } = fitnessData;
        submittedTypeData[JournalType.FITNESS] = sanitizedFitnessData;
      }

      const result = await createJournal({
        title: values.title,
        content: values.content,
        // Each bound is the UTC instant of midnight on its day in the zone the
        // journal itself records, and the end is the last day inclusive. Taken
        // from the event data being submitted rather than from the user's
        // settings, because that is the zone the backend and the Google sync
        // will read these bounds back through: the two travel in one request
        // and must agree, or the event lands on the wrong day (issue #1401).
        event_date_range: {
          start: zonedMidnight(
            values.dateRange.from,
            rangeTimezone
          ).toISOString(),
          end: zonedMidnight(endDate, rangeTimezone).toISOString(),
        },
        types: values.types,
        parent_id: values.parentId ?? undefined,
        ...(Object.keys(submittedTypeData).length > 0 && {
          type_data: submittedTypeData,
        }),
      });

      // Upload pending routes sequentially now that we have a journal ID
      for (const route of pendingRoutes) {
        try {
          await createRoute({
            journalId: result.data.id,
            data: {
              name: route.name,
              gpx_data: route.gpx_data,
            },
            silent: true,
          });
        } catch (error) {
          console.error(`Failed to upload GPX track: ${route.name}`, error);
          toast.error(
            `Journal created, but failed to upload GPX track: ${route.name}`
          );
        }
      }

      if (onSuccess) {
        onSuccess(result.data.id);
      } else {
        router.push(`/journals/${result.data.id}` as Route);
      }
    } catch (error) {
      console.error('Failed to create journal:', error);
      // Log validation errors from hook form if any
      console.error('Form errors:', form.formState.errors);
    }
  };

  const handleCancel = () => {
    if (onCancel) {
      onCancel();
    } else {
      router.push('/journals' as Route);
    }
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-6'>
        <FormField
          control={form.control}
          name='title'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Title</FormLabel>
              <FormControl>
                <Input placeholder='Enter journal title' {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='parentId'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Parent Journal</FormLabel>
              <FormControl>
                <JournalSearchCombobox
                  onSelect={journal => {
                    parentUserModified.current = true;
                    field.onChange(Number.parseInt(journal.id, 10));
                  }}
                  onClear={() => {
                    parentUserModified.current = true;
                    field.onChange(null);
                  }}
                  onSearchChange={() => {
                    parentUserModified.current = true;
                  }}
                  placeholder='Search for a parent journal...'
                  value={
                    parentUserModified.current ? undefined : defaultParentTitle
                  }
                  className='w-full'
                />
              </FormControl>
              <FormDescription>
                Optional: Link this journal entry to a parent entry
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='dateRange'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Date Range</FormLabel>
              <FormControl>
                <div className='flex items-center gap-4'>
                  <div className='flex w-full flex-col gap-2'>
                    <Label
                      htmlFor='date-range-start'
                      className='text-muted-foreground text-xs'
                    >
                      Start Date
                    </Label>
                    <Input
                      id='date-range-start'
                      type='date'
                      value={formatLocalDate(field.value.from)}
                      onChange={e => {
                        const newDate = parseLocalDate(e.target.value);
                        // If 'to' is not set, or is the same as the old 'from', auto-advance 'to' to match the new 'from'
                        const autoUpdateTo =
                          !field.value.to ||
                          field.value.to.getTime() ===
                            field.value.from.getTime();
                        field.onChange({
                          ...field.value,
                          from: newDate,
                          ...(autoUpdateTo ? { to: newDate } : {}),
                        });
                      }}
                      className='w-full'
                    />
                  </div>
                  <div className='flex w-full flex-col gap-2'>
                    <Label
                      htmlFor='date-range-end'
                      className='text-muted-foreground text-xs'
                    >
                      End Date
                    </Label>
                    <Input
                      id='date-range-end'
                      type='date'
                      value={formatLocalDate(
                        field.value.to || field.value.from
                      )}
                      onChange={e => {
                        const newDate = parseLocalDate(e.target.value);
                        field.onChange({ ...field.value, to: newDate });
                      }}
                      className='w-full'
                      min={formatLocalDate(field.value.from)}
                    />
                  </div>
                </div>
              </FormControl>
              <FormDescription>
                Select the start and end date for this journal entry
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='content'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Content</FormLabel>
              <FormControl>
                <MarkdownEditor
                  value={field.value ?? ''}
                  onChange={field.onChange}
                  placeholder='Write your journal entry...'
                  aria-label='Content'
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='types'
          render={() => (
            <FormItem>
              <div className='mb-4'>
                <FormLabel>Journal Types</FormLabel>
                <FormDescription>
                  Select one or more types for this journal entry
                </FormDescription>
              </div>
              <div className='space-y-2'>
                {typeOptions.map(option => (
                  <TypeCheckboxField
                    key={option.value}
                    control={form.control}
                    option={option}
                  />
                ))}
              </div>
              <FormMessage />
            </FormItem>
          )}
        />

        {/* Dependency information and inline editors for selected types */}
        {selectedTypes.length > 0 && (
          <div className='space-y-4'>
            {selectedTypes.map(type => {
              const deps = TYPE_DEPENDENCIES[type];
              const typeTestId = getJournalTypeTestId(type);
              return (
                <Card
                  key={type}
                  className='border-border/80 shadow-sm'
                  data-testid={`selected-type-panel-${typeTestId}`}
                >
                  <CardHeader className='space-y-3 pb-4'>
                    <div className='space-y-1'>
                      <CardTitle className='text-base'>
                        {TYPE_LABELS[type]}
                      </CardTitle>
                      <CardDescription>
                        Add the details for this journal type.
                      </CardDescription>
                    </div>

                    {deps && deps.length > 0 && (
                      <div className='space-y-2'>
                        <p className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>
                          Automatically adds
                        </p>
                        <div className='flex flex-wrap gap-2'>
                          {deps.map(dep => (
                            <Badge
                              key={dep}
                              variant='secondary'
                              data-testid={`selected-type-dependency-${typeTestId}-${getJournalTypeTestId(dep)}`}
                            >
                              {TYPE_LABELS[dep]}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardHeader>

                  <CardContent className='pt-0'>
                    {type === JournalType.EVENT && (
                      <EventTypeEditor
                        createMode
                        onChange={handleEventChange}
                      />
                    )}
                    {type === JournalType.MOOD_RATING && (
                      <MoodRatingTypeEditor
                        createMode
                        onChange={handleMoodRatingChange}
                      />
                    )}
                    {type === JournalType.PLAN && (
                      <PlanTypeEditor createMode onChange={handlePlanChange} />
                    )}
                    {type === JournalType.TRAVEL && (
                      <TravelTypeEditor
                        createMode
                        onChange={handleTravelChange}
                      />
                    )}
                    {type === JournalType.FITNESS && (
                      <FitnessTypeEditor
                        createMode
                        onChange={handleFitnessChange}
                      />
                    )}
                    {type === JournalType.OUTDOOR_ACTIVITY && (
                      <OutdoorActivityTypeEditor
                        createMode
                        onChange={handleOutdoorActivityChange}
                      />
                    )}
                    {type === JournalType.JOGGING && (
                      <JoggingTypeEditor
                        createMode
                        onChange={handleJoggingChange}
                      />
                    )}
                    {type === JournalType.BUSHWALKING && (
                      <BushwalkingTypeEditor
                        createMode
                        onChange={handleBushwalkingChange}
                      />
                    )}
                    {type === JournalType.ABSEILING_TRIP && (
                      <AbseilingTripTypeEditor
                        key={abseilKey}
                        createMode
                        data={typeData[JournalType.ABSEILING_TRIP]}
                        onChange={handleAbseilingTripChange}
                        onTemplateSelect={handleTemplateSelect}
                        templateTypes={templateTypesForJournalTypes(
                          selectedTypes
                        )}
                      />
                    )}
                    {type === JournalType.CANYONING && (
                      <CanyoningTypeEditor
                        key={abseilKey}
                        createMode
                        data={templateSeedData[JournalType.CANYONING]}
                        onChange={handleCanyoningChange}
                      />
                    )}
                    {type === JournalType.CAVING && (
                      <CavingTypeEditor
                        key={abseilKey}
                        createMode
                        data={templateSeedData[JournalType.CAVING]}
                        onChange={handleCavingChange}
                      />
                    )}
                    {type === JournalType.CANOEING && (
                      <CanoeingTypeEditor
                        createMode
                        onChange={handleCanoeingChange}
                      />
                    )}
                    {type === JournalType.CLIMBING && (
                      <ClimbingTypeEditor
                        key={abseilKey}
                        createMode
                        data={templateSeedData[JournalType.CLIMBING]}
                        onChange={handleClimbingChange}
                      />
                    )}
                    {type === JournalType.KAYAKING && (
                      <KayakingTypeEditor
                        createMode
                        onChange={handleKayakingChange}
                      />
                    )}
                    {type === JournalType.CROSS_COUNTRY_SKIING && (
                      <CrossCountrySkiingTypeEditor
                        createMode
                        onChange={handleCrossCountrySkiingChange}
                      />
                    )}
                    {type === JournalType.SNORKELLING && (
                      <SnorkellingTypeEditor
                        createMode
                        onChange={handleSnorkellingChange}
                      />
                    )}
                    {type === JournalType.DIVING && (
                      <DivingTypeEditor
                        createMode
                        onChange={handleDivingChange}
                      />
                    )}
                    {type === JournalType.DOWNHILL_SKIING && (
                      <DownhillSkiingTypeEditor
                        createMode
                        onChange={handleDownhillSkiingChange}
                      />
                    )}
                    {type === JournalType.OUTDOOR_PLANNING && (
                      <OutdoorPlanningTypeEditor
                        createMode
                        onChange={handleOutdoorPlanningChange}
                      />
                    )}
                    {type === JournalType.OUTDOOR_TRAINING && (
                      <OutdoorTrainingTypeEditor
                        createMode
                        onChange={handleOutdoorTrainingChange}
                      />
                    )}
                    {type === JournalType.GEAR_MAINTENANCE && (
                      <GearMaintenanceTypeEditor
                        createMode
                        onChange={handleGearMaintenanceChange}
                      />
                    )}
                    {type === JournalType.GEAR_USAGE && (
                      <GearUsageTypeEditor
                        createMode
                        onChange={handleGearUsageChange}
                      />
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        <div className='flex gap-4'>
          <Button type='submit' disabled={isPending}>
            {isPending ? 'Creating...' : 'Create Journal'}
          </Button>
          <Button type='button' variant='outline' onClick={handleCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Form>
  );
}
