'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { KeyRound, Loader2, Link as LinkIcon, Unplug } from 'lucide-react';
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
import { useImmichConnect, useImmichDisconnect } from '@/lib/api/integrations';

const immichSettingsSchema = z.object({
  server_url: z
    .string()
    .min(1, 'Server URL is required')
    .url('Must be a valid URL (e.g. https://immich.example.com)'),
  api_key: z.string().min(1, 'API Key is required'),
});

type ImmichSettingsFormValues = z.infer<typeof immichSettingsSchema>;

interface ImmichSettingsProps {
  connected?: boolean;
}

export function ImmichSettings({ connected = false }: ImmichSettingsProps) {
  const connectImmich = useImmichConnect();
  const disconnectImmich = useImmichDisconnect();

  const form = useForm<ImmichSettingsFormValues>({
    resolver: zodResolver(immichSettingsSchema),
    defaultValues: {
      server_url: '',
      api_key: '',
    },
  });

  const onSubmit = (values: ImmichSettingsFormValues) => {
    connectImmich.mutate(
      {
        server_url: values.server_url.trim(),
        api_key: values.api_key.trim(),
      },
      {
        onSuccess: () => {
          form.reset();
        },
      }
    );
  };

  const handleDisconnect = () => {
    disconnectImmich.mutate();
  };

  if (connected) {
    return (
      <div className='space-y-6'>
        <div className='border-success/30 bg-success/10 rounded-lg border p-4'>
          <div className='flex items-start'>
            <div className='flex-shrink-0'>
              <div className='bg-success/15 flex h-8 w-8 items-center justify-center rounded-full'>
                <LinkIcon className='text-success h-4 w-4' />
              </div>
            </div>
            <div className='ml-3'>
              <h3 className='text-success text-sm font-medium'>
                Successfully Connected to Immich
              </h3>
              <div className='text-success mt-2 text-sm'>
                <p>
                  Your account is securely connected. You can now synchronize
                  contacts and import albums.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className='flex gap-2 pt-2'>
          <Button
            type='button'
            variant='destructive'
            onClick={handleDisconnect}
            disabled={disconnectImmich.isPending}
            data-testid='immich-disconnect-button'
          >
            {disconnectImmich.isPending ? (
              <Loader2 className='mr-2 h-4 w-4 animate-spin' />
            ) : (
              <Unplug className='mr-2 h-4 w-4' />
            )}
            Disconnect Integration
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className='space-y-6'
        data-testid='immich-settings-form'
      >
        <FormField
          control={form.control}
          name='server_url'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Immich Server URL</FormLabel>
              <FormControl>
                <Input
                  placeholder='https://immich.example.com'
                  data-testid='immich-server-url-input'
                  {...field}
                />
              </FormControl>
              <FormDescription>
                The base URL of your self-hosted Immich instance.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='api_key'
          render={({ field }) => (
            <FormItem>
              <FormLabel>
                <KeyRound className='mr-1 inline h-4 w-4' />
                API Key
              </FormLabel>
              <FormControl>
                <Input
                  type='password'
                  placeholder='Enter your Immich API key'
                  data-testid='immich-api-key-input'
                  {...field}
                />
              </FormControl>
              <FormDescription>
                Generate an API key in your Immich account settings under{' '}
                <strong>Account Settings → API Keys</strong>. The key is stored
                encrypted.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <div className='flex gap-2'>
          <Button
            type='submit'
            disabled={connectImmich.isPending}
            data-testid='immich-connect-button'
          >
            {connectImmich.isPending ? (
              <>
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                Connecting...
              </>
            ) : (
              <>
                <LinkIcon className='mr-2 h-4 w-4' />
                Connect to Immich
              </>
            )}
          </Button>
        </div>
      </form>
    </Form>
  );
}
