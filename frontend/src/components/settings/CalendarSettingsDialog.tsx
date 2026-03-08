'use client';

import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useCreateCalendar, useUpdateCalendar } from '@/lib/api/journals';
import { JournalCalendar } from '@/types/journals';

const calendarFormSchema = z.object({
  name: z.string().min(1, 'Name is required').max(100),
  description: z.string().max(500).optional().nullable(),
  color: z
    .string()
    .min(1, 'Color is required')
    .regex(/^#[0-9A-Fa-f]{6}$/, 'Must be a valid hex color'),
  is_synced_to_google: z.boolean(),
});

type CalendarFormValues = z.infer<typeof calendarFormSchema>;

interface CalendarSettingsDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly calendar?: JournalCalendar;
}

export function CalendarSettingsDialog({
  open,
  onOpenChange,
  calendar,
}: CalendarSettingsDialogProps) {
  const isEditing = !!calendar;

  const { mutateAsync: createCalendar, isPending: isCreating } =
    useCreateCalendar();
  const { mutateAsync: updateCalendar, isPending: isUpdating } =
    useUpdateCalendar();

  const form = useForm<CalendarFormValues>({
    resolver: zodResolver(calendarFormSchema),
    defaultValues: {
      name: '',
      description: '',
      color: '#3b82f6', // default blue
      is_synced_to_google: false,
    },
  });

  useEffect(() => {
    if (open) {
      if (calendar) {
        form.reset({
          name: calendar.name,
          description: calendar.description || '',
          color: calendar.color || '#3b82f6',
          is_synced_to_google: calendar.is_synced_to_google || false,
        });
      } else {
        form.reset({
          name: '',
          description: '',
          color: '#3b82f6',
          is_synced_to_google: false,
        });
      }
    }
  }, [open, calendar, form]);

  const onSubmit = async (values: CalendarFormValues) => {
    try {
      if (isEditing) {
        await updateCalendar({ id: calendar.id, data: values });
      } else {
        await createCalendar(values);
      }
      onOpenChange(false);
    } catch (error) {
      // Error is handled by the mutation hooks (toast)
      console.error('Failed to save calendar', error);
    }
  };

  const isPending = isCreating || isUpdating;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-[425px]'>
        <DialogHeader>
          <DialogTitle>
            {isEditing ? 'Edit Calendar' : 'Create Calendar'}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? 'Update the details for this calendar.'
              : 'Add a new calendar to organize your journals.'}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-4'>
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder='Personal, Work, etc.' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder='Optional details about this calendar'
                      className='resize-none'
                      {...field}
                      value={field.value || ''}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='color'
              render={({ field }) => (
                <FormItem className='flex flex-col'>
                  <FormLabel>Color</FormLabel>
                  <div className='flex items-center gap-3'>
                    <Input
                      type='color'
                      aria-label='Color picker'
                      className='h-10 w-12 cursor-pointer p-1'
                      value={field.value || '#000000'}
                      onChange={e => field.onChange(e.target.value)}
                    />
                    <FormControl>
                      <Input
                        type='text'
                        className='w-28 font-mono uppercase'
                        data-testid='color-input'
                        {...field}
                      />
                    </FormControl>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='is_synced_to_google'
              render={({ field }) => (
                <FormItem className='flex flex-row items-center justify-between rounded-lg border p-3 shadow-sm'>
                  <div className='space-y-0.5'>
                    <FormLabel>Google Sync</FormLabel>
                    <FormDescription>
                      Sync events to your Google Calendar
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={true} // Disabled for now as per requirements
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter className='pt-4'>
              <Button
                type='button'
                variant='outline'
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type='submit' disabled={isPending}>
                {isPending ? 'Saving...' : 'Save Changes'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
