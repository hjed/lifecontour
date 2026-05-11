'use client';

import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  useSnipeItSettings,
  useSaveSnipeItSettings,
} from '@/lib/api/integrations';

const snipeItSettingsSchema = z.object({
  base_url: z
    .string()
    .min(1, 'Base URL is required')
    .url('Must be a valid URL (e.g. https://snipeit.example.com)'),
  snipeit_user_id: z.string().optional().nullable(),
});

type SnipeItSettingsFormValues = z.infer<typeof snipeItSettingsSchema>;

export function SnipeItSettings() {
  const { data: settings, isLoading, isError } = useSnipeItSettings();
  const saveSettings = useSaveSnipeItSettings();

  const form = useForm<SnipeItSettingsFormValues>({
    resolver: zodResolver(snipeItSettingsSchema),
    defaultValues: {
      base_url: '',
      snipeit_user_id: '',
    },
  });

  // Populate form when settings are loaded
  useEffect(() => {
    if (settings) {
      form.reset({
        base_url: settings.base_url ?? '',
        snipeit_user_id: settings.snipeit_user_id ?? '',
      });
    }
  }, [settings, form]);

  const onSubmit = (values: SnipeItSettingsFormValues) => {
    saveSettings.mutate({
      base_url: values.base_url,
      snipeit_user_id: values.snipeit_user_id || null,
    });
  };

  if (isLoading) {
    return (
      <div className='flex items-center justify-center py-8'>
        <Loader2 className='h-6 w-6 animate-spin' />
        <span className='ml-2'>Loading settings...</span>
      </div>
    );
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className='space-y-6'
        data-testid='snipeit-settings-form'
      >
        <FormField
          control={form.control}
          name='base_url'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Snipe-IT Base URL</FormLabel>
              <FormControl>
                <Input
                  placeholder='https://snipeit.example.com'
                  data-testid='snipeit-base-url-input'
                  {...field}
                />
              </FormControl>
              <FormDescription>
                The URL of your self-hosted Snipe-IT instance. This is used for
                API communication and OAuth configuration.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='snipeit_user_id'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Snipe-IT User ID</FormLabel>
              <FormControl>
                <Input
                  placeholder='e.g. 42'
                  data-testid='snipeit-user-id-input'
                  {...field}
                  value={field.value ?? ''}
                />
              </FormControl>
              <FormDescription>
                Your user ID in Snipe-IT. This maps your PMS account to your
                Snipe-IT user for checkout and assignment operations.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {isError && !settings && (
          <p className='text-muted-foreground text-sm'>
            No settings configured yet. Enter your Snipe-IT details to get
            started.
          </p>
        )}

        <Button
          type='submit'
          disabled={saveSettings.isPending}
          data-testid='snipeit-settings-save-button'
        >
          {saveSettings.isPending ? (
            <>
              <Loader2 className='mr-2 h-4 w-4 animate-spin' />
              Saving...
            </>
          ) : (
            'Save Settings'
          )}
        </Button>
      </form>
    </Form>
  );
}
