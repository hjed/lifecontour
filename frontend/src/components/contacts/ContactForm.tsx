/**
 * Simple contact form component for creating and editing contacts.
 *
 * Basic form for essential contact information only.
 */

'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Save } from 'lucide-react';
import { ContactFormData } from '@/types/contacts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { VALIDATION_MESSAGES } from '@/lib/constants';

// Simplified form validation schema - just basic contact info
const contactFormSchema = z.object({
  first_name: z.string().min(1, VALIDATION_MESSAGES.REQUIRED_FIELD),
  last_name: z.string().optional(),
  middle_name: z.string().optional(),
  nick_name: z.string().optional(),
});

type ContactFormValues = z.infer<typeof contactFormSchema>;

interface ContactFormProps {
  readonly initialData?: ContactFormData;
  readonly onSubmit: (data: ContactFormData) => Promise<void>;
  readonly onCancel?: () => void;
  readonly isLoading?: boolean;
}

export function ContactForm({
  initialData,
  onSubmit,
  onCancel,
  isLoading,
}: ContactFormProps) {
  const form = useForm<ContactFormValues>({
    resolver: zodResolver(contactFormSchema),
    defaultValues: {
      first_name: initialData?.first_name || '',
      last_name: initialData?.last_name || '',
      middle_name: initialData?.middle_name || '',
      nick_name: initialData?.nick_name || '',
    },
  });

  const handleSubmit = async (data: ContactFormValues) => {
    try {
      // Convert form data to ContactFormData format
      const contactData: ContactFormData = {
        first_name: data.first_name,
        last_name: data.last_name,
        middle_name: data.middle_name,
        nick_name: data.nick_name,
        contact_methods: initialData?.contact_methods || [],
        addresses: initialData?.addresses || [],
        notes: initialData?.notes || [],
      };

      await onSubmit(contactData);
    } catch (error) {
      // Error handling is done by the parent component
      console.error('Form submission error:', error);
    }
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(handleSubmit)} className='space-y-6'>
        {/* Name Fields - Styled to match detail view */}
        <div className='space-y-4'>
          <div>
            <h3 className='mb-3 text-lg font-medium'>Contact Name</h3>
            <div className='grid gap-4 md:grid-cols-2'>
              <FormField
                control={form.control}
                name='first_name'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>First Name *</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        data-testid='first-name-input'
                        className='text-base'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='last_name'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Last Name</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        data-testid='last-name-input'
                        className='text-base'
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </div>

          <div className='grid gap-4 md:grid-cols-2'>
            <FormField
              control={form.control}
              name='middle_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Middle Name</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      data-testid='middle-name-input'
                      className='text-base'
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='nick_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nickname</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      data-testid='nickname-input'
                      className='text-base'
                      placeholder='Optional nickname'
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
        </div>

        {/* Form Actions */}
        <div className='flex justify-end gap-2 border-t pt-4'>
          {onCancel && (
            <Button
              type='button'
              variant='outline'
              onClick={onCancel}
              disabled={isLoading}
            >
              Cancel
            </Button>
          )}
          <Button
            type='submit'
            disabled={isLoading}
            data-testid='save-contact-button'
          >
            <Save className='mr-2 h-4 w-4' />
            {isLoading ? 'Saving...' : 'Save Contact'}
          </Button>
        </div>
      </form>
    </Form>
  );
}
