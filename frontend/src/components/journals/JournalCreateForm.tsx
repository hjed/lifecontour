/**
 * Form component for creating a new journal entry.
 *
 * Provides fields for title, date range, content, and type selection.
 * Handles validation and submission via the journals API.
 */

'use client';

import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useForm } from 'react-hook-form';
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
import { JournalType } from '@/types/journals';

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

// Type options for checkboxes
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
];

interface JournalCreateFormProps {
  readonly onCancel?: () => void;
}

export function JournalCreateForm({ onCancel }: JournalCreateFormProps = {}) {
  const router = useRouter();
  const { mutateAsync: createJournal, isPending } = useCreateJournal();

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

  const onSubmit = async (values: FormValues) => {
    try {
      // Convert form values to API format
      const endDate = values.dateRange.to || values.dateRange.from;

      const result = await createJournal({
        title: values.title,
        content: values.content,
        event_date_range: {
          start: values.dateRange.from.toISOString(),
          end: endDate.toISOString(),
        },
        types: values.types,
      });

      // Redirect to the newly created journal
      router.push(`/journals/${result.data.id}` as Route);
    } catch (error) {
      console.error('Failed to create journal:', error);
      // Error handling will be improved in future iterations
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
                  <FormField
                    key={option.value}
                    control={form.control}
                    name='types'
                    render={({ field }) => (
                      <FormItem
                        key={option.value}
                        className='flex flex-row items-start space-y-0 space-x-3'
                      >
                        <FormControl>
                          <Checkbox
                            checked={field.value?.includes(option.value)}
                            onCheckedChange={checked => {
                              return checked
                                ? field.onChange([...field.value, option.value])
                                : field.onChange(
                                    field.value?.filter(
                                      value => value !== option.value
                                    )
                                  );
                            }}
                          />
                        </FormControl>
                        <FormLabel className='font-normal'>
                          {option.label}
                        </FormLabel>
                      </FormItem>
                    )}
                  />
                ))}
              </div>
              <FormMessage />
            </FormItem>
          )}
        />

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
