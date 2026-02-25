/**
 * Form component for creating a new journal entry.
 *
 * Provides fields for title, date range, content, and type selection.
 * Shows inline type editors for selected types (in create mode).
 * Handles validation and submission via the journals API.
 */

'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useForm, type Control } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
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
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { useCreateJournal } from '@/lib/api/journals';
import {
  JournalType,
  type CalendarInfoData,
  type JournalTypeData,
  type MoodData,
  type PlanData,
  type TravelData,
  type PhotoAlbumData,
} from '@/types/journals';
import {
  EventTypeEditor,
  MoodRatingTypeEditor,
  PlanTypeEditor,
  TravelTypeEditor,
  PhotoAlbumTypeEditor,
} from './type-editors';

// Form validation schema
const formSchema = z.object({
  title: z.string().min(1, 'Title is required'),
  dateRange: z.object({
    from: z.date(),
    to: z.date().optional(),
  }),
  content: z.string(),
  types: z.array(z.nativeEnum(JournalType)),
});

type FormValues = z.infer<typeof formSchema>;

// Type-specific data collected from inline editors
interface TypeDataState {
  [JournalType.EVENT]?: CalendarInfoData;
  [JournalType.MOOD_RATING]?: MoodData;
  [JournalType.PLAN]?: PlanData;
  [JournalType.TRAVEL]?: TravelData;
  [JournalType.PHOTO_ALBUM]?: PhotoAlbumData;
}

// All 15 journal type options for checkboxes
const typeOptions = [
  { value: JournalType.NOTE, label: 'Note' },
  { value: JournalType.EVENT, label: 'Event' },
  { value: JournalType.MOOD_RATING, label: 'Mood Rating' },
  { value: JournalType.PLAN, label: 'Plan' },
  { value: JournalType.TRAVEL, label: 'Travel' },
  { value: JournalType.PHOTO_ALBUM, label: 'Photo Album' },
  { value: JournalType.FITNESS, label: 'Fitness' },
  { value: JournalType.OUTDOOR_ACTIVITY, label: 'Outdoor Activity' },
  { value: JournalType.BUSHWALKING, label: 'Bushwalking' },
  { value: JournalType.JOGGING, label: 'Jogging' },
  { value: JournalType.ABSEILING_TRIP, label: 'Abseiling Trip' },
  { value: JournalType.CANYONING, label: 'Canyoning' },
  { value: JournalType.CLIMBING, label: 'Climbing' },
  { value: JournalType.KAYAKING, label: 'Kayaking' },
  { value: JournalType.CROSS_COUNTRY_SKIING, label: 'Cross-Country Skiing' },
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
  [JournalType.CLIMBING]: [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS],
  [JournalType.KAYAKING]: [JournalType.OUTDOOR_ACTIVITY, JournalType.FITNESS],
  [JournalType.CROSS_COUNTRY_SKIING]: [
    JournalType.BUSHWALKING,
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
                const newValue = checked
                  ? [...field.value, option.value]
                  : field.value?.filter(v => v !== option.value);
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
const TYPE_LABELS: Record<JournalType, string> = {
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
  [JournalType.CLIMBING]: 'Climbing',
  [JournalType.KAYAKING]: 'Kayaking',
  [JournalType.CROSS_COUNTRY_SKIING]: 'Cross-Country Skiing',
};

interface JournalCreateFormProps {
  readonly onCancel?: () => void;
}

export function JournalCreateForm({ onCancel }: JournalCreateFormProps = {}) {
  const router = useRouter();
  const { mutateAsync: createJournal, isPending } = useCreateJournal();
  const [typeData, setTypeData] = useState<TypeDataState>({});

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      title: '',
      dateRange: {
        from: new Date(),
        to: undefined,
      },
      content: '',
      types: [],
    },
  });

  const selectedTypes = form.watch('types');

  const handleTypeDataChange = useCallback(
    <K extends keyof TypeDataState>(type: K, data: TypeDataState[K]) => {
      setTypeData(prev => ({ ...prev, [type]: data }));
    },
    []
  );

  const onSubmit = async (values: FormValues) => {
    try {
      const endDate = values.dateRange.to || values.dateRange.from;

      // Build type_data from collected editor data for selected types
      const submittedTypeData: Record<string, JournalTypeData> = {};
      for (const type of values.types) {
        const data = typeData[type as keyof TypeDataState];
        if (data !== undefined) {
          submittedTypeData[type] = data;
        }
      }

      const result = await createJournal({
        title: values.title,
        content: values.content,
        event_date_range: {
          start: values.dateRange.from.toISOString(),
          end: endDate.toISOString(),
        },
        types: values.types,
        ...(Object.keys(submittedTypeData).length > 0 && {
          type_data: submittedTypeData,
        }),
      });

      router.push(`/journals/${result.data.id}` as Route);
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
          name='dateRange'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Date Range</FormLabel>
              <FormControl>
                {/* Placeholder for date range picker - will be implemented in future iteration */}
                <Input
                  type='date'
                  value={field.value.from.toISOString().split('T')[0]}
                  onChange={e => {
                    const newDate = new Date(e.target.value);
                    field.onChange({ ...field.value, from: newDate });
                  }}
                />
              </FormControl>
              <FormDescription>
                Select the date or date range for this journal entry
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
                <Textarea
                  placeholder='Write your journal entry...'
                  className='min-h-[200px]'
                  {...field}
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
              return (
                <div key={type} className='space-y-3 rounded-md border p-4'>
                  <p className='text-sm font-medium'>{TYPE_LABELS[type]}</p>

                  {deps && deps.length > 0 && (
                    <p className='text-muted-foreground text-xs'>
                      Automatically adds:{' '}
                      {deps.map(dep => TYPE_LABELS[dep]).join(', ')}
                    </p>
                  )}

                  {type === JournalType.EVENT && (
                    <EventTypeEditor
                      createMode
                      onChange={data =>
                        handleTypeDataChange(JournalType.EVENT, data)
                      }
                    />
                  )}
                  {type === JournalType.MOOD_RATING && (
                    <MoodRatingTypeEditor
                      createMode
                      onChange={data =>
                        handleTypeDataChange(JournalType.MOOD_RATING, data)
                      }
                    />
                  )}
                  {type === JournalType.PLAN && (
                    <PlanTypeEditor
                      createMode
                      onChange={data =>
                        handleTypeDataChange(JournalType.PLAN, data)
                      }
                    />
                  )}
                  {type === JournalType.TRAVEL && (
                    <TravelTypeEditor
                      createMode
                      onChange={data =>
                        handleTypeDataChange(JournalType.TRAVEL, data)
                      }
                    />
                  )}
                  {type === JournalType.PHOTO_ALBUM && (
                    <PhotoAlbumTypeEditor
                      createMode
                      onChange={data =>
                        handleTypeDataChange(JournalType.PHOTO_ALBUM, data)
                      }
                    />
                  )}
                </div>
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
