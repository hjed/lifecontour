'use client';

import { FileWarning, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useDeadLetters } from '@/lib/api/integrations';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

export function DeadLetterQueue() {
  const { data, isLoading, error } = useDeadLetters(10, 0);

  if (isLoading) {
    return (
      <Card className='mt-6'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <FileWarning className='h-5 w-5 text-gray-500' />
            Dead-Letter Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className='text-muted-foreground text-sm'>
            Loading dead-letter events...
          </p>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className='mt-6'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <FileWarning className='h-5 w-5 text-gray-500' />
            Dead-Letter Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant='destructive'>
            <AlertCircle className='h-4 w-4' />
            <AlertTitle>Error fetching dead letters</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const items = data?.items || [];
  const total = data?.total || 0;

  return (
    <Card className='mt-6' data-testid='dead-letter-queue'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <FileWarning className='h-5 w-5 text-amber-500' />
          Dead-Letter Queue ({total})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className='text-muted-foreground text-sm'>
            No dead-letter events found.
          </p>
        ) : (
          <div className='space-y-4'>
            {items.map(item => (
              <div key={item.id} className='rounded-lg border p-3 text-sm'>
                <div className='mb-2 flex items-start justify-between'>
                  <span className='font-medium'>{item.event_type}</span>
                  <span className='text-muted-foreground text-xs'>
                    {item.created_at
                      ? new Date(item.created_at).toLocaleString()
                      : 'Unknown time'}
                  </span>
                </div>
                <div className='text-muted-foreground mb-1'>
                  Consumer: {item.consumer_group} | Retries:{' '}
                  {item.delivery_count}
                </div>
                <div className='bg-destructive/10 text-destructive rounded p-2 text-xs break-words'>
                  {item.last_error}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
