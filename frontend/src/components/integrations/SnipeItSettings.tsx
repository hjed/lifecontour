'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { KeyRound, Loader2, Settings, Unplug } from 'lucide-react';
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
  useSnipeItConnect,
  useSnipeItDisconnect,
} from '@/lib/api/integrations';
import { APP_NAME } from '@/lib/constants';

const snipeItSettingsSchema = z.object({
  base_url: z
    .string()
    .min(1, 'Base URL is required')
    .url('Must be a valid URL (e.g. https://snipeit.example.com)'),
  snipeit_user_id: z.string().optional().nullable(),
  api_key: z.string().optional(),
});

type SnipeItSettingsFormValues = z.infer<typeof snipeItSettingsSchema>;

interface SnipeItSettingsProps {
  connected?: boolean;
}

export function SnipeItSettings({ connected = false }: SnipeItSettingsProps) {
  const { data: settings, isLoading, isError, error } = useSnipeItSettings();
  const saveSettings = useSaveSnipeItSettings();
  const connectSnipeIt = useSnipeItConnect();
  const disconnectSnipeIt = useSnipeItDisconnect();
  const [showApiKey, setShowApiKey] = useState(false);

  const form = useForm<SnipeItSettingsFormValues>({
    resolver: zodResolver(snipeItSettingsSchema),
    defaultValues: {
      base_url: '',
      snipeit_user_id: '',
      api_key: '',
    },
  });

  // Populate form when settings are loaded
  useEffect(() => {
    if (settings) {
      form.reset({
        base_url: settings.base_url ?? '',
        snipeit_user_id: settings.snipeit_user_id ?? '',
        api_key: '',
      });
    }
  }, [settings, form]);

  const onSubmit = (values: SnipeItSettingsFormValues) => {
    // Save base URL and user ID settings first
    saveSettings.mutate(
      {
        base_url: values.base_url,
        snipeit_user_id: values.snipeit_user_id || null,
      },
      {
        onSuccess: () => {
          // If an API key was provided, connect with it
          if (values.api_key && values.api_key.trim()) {
            connectSnipeIt.mutate({ api_key: values.api_key.trim() });
            // Clear the API key field after submission
            form.setValue('api_key', '');
            setShowApiKey(false);
          }
        },
      }
    );
  };

  const handleDisconnect = () => {
    disconnectSnipeIt.mutate();
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
                API communication.
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
                Your user ID in Snipe-IT. This maps your {APP_NAME} account to
                your Snipe-IT user for checkout and assignment operations.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {/* API Key field — shown when not connected or when user clicks "Update API Key" */}
        {(!connected || showApiKey) && (
          <FormField
            control={form.control}
            name='api_key'
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  <KeyRound className='mr-1 inline h-4 w-4' />
                  API Key (Personal Access Token)
                </FormLabel>
                <FormControl>
                  <Input
                    type='password'
                    placeholder={
                      connected
                        ? 'Enter new API key to update'
                        : 'Paste your Snipe-IT personal access token'
                    }
                    data-testid='snipeit-api-key-input'
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  Generate a personal access token in your Snipe-IT admin panel
                  under <strong>Admin → API Keys</strong>. The key is stored
                  encrypted and never displayed again.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        {isError &&
          !settings &&
          (error as Error)?.message?.includes('No Snipe-IT settings found') && (
            <p className='text-muted-foreground text-sm'>
              No settings configured yet. Enter your Snipe-IT details to get
              started.
            </p>
          )}
        {isError &&
          !settings &&
          !(error as Error)?.message?.includes(
            'No Snipe-IT settings found'
          ) && (
            <p className='text-sm text-red-500'>
              Failed to load settings. Please try again later.
            </p>
          )}

        <div className='flex gap-2'>
          <Button
            type='submit'
            disabled={saveSettings.isPending || connectSnipeIt.isPending}
            data-testid='snipeit-settings-save-button'
          >
            {saveSettings.isPending || connectSnipeIt.isPending ? (
              <>
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                Saving...
              </>
            ) : (
              <>
                <Settings className='mr-2 h-4 w-4' />
                {connected ? 'Save Settings' : 'Save & Connect'}
              </>
            )}
          </Button>

          {connected && !showApiKey && (
            <Button
              type='button'
              variant='outline'
              onClick={() => setShowApiKey(true)}
              data-testid='snipeit-update-api-key-button'
            >
              <KeyRound className='mr-2 h-4 w-4' />
              Update API Key
            </Button>
          )}

          {connected && (
            <Button
              type='button'
              variant='destructive'
              onClick={handleDisconnect}
              disabled={disconnectSnipeIt.isPending}
              data-testid='snipeit-disconnect-button'
            >
              {disconnectSnipeIt.isPending ? (
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
              ) : (
                <Unplug className='mr-2 h-4 w-4' />
              )}
              Disconnect
            </Button>
          )}
        </div>
      </form>
    </Form>
  );
}
