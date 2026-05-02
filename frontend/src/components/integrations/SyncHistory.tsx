import { useState } from 'react';
import { History, Clock, AlertCircle } from 'lucide-react';
import { useSyncHistory } from '@/lib/api/integrations';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';

function formatDateSafely(dateString: string | null): string {
  if (!dateString) return 'Never';
  try {
    return format(new Date(dateString), 'PPp', { locale: enAU });
  } catch {
    return 'Invalid date';
  }
}

function getSyncStatusVariant(
  status: string
): 'default' | 'destructive' | 'secondary' {
  if (status === 'completed') return 'default';
  if (status === 'failed') return 'destructive';
  return 'secondary';
}

export interface SyncHistoryProps {
  integrationId: string;
}

export function SyncHistory({ integrationId }: SyncHistoryProps) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useSyncHistory(
    integrationId,
    { limit: 10 },
    open
  );

  const recentJobs = data?.data || [];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' size='sm' className='gap-2'>
          <History className='h-4 w-4' />
          Sync History
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[80vh] max-w-2xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            <Clock className='h-5 w-5 text-blue-500' />
            Sync History
          </DialogTitle>
        </DialogHeader>

        <div className='mt-4'>
          {isLoading ? (
            <div className='space-y-2'>
              {[1, 2, 3].map(val => (
                <Skeleton key={`skeleton-${val}`} className='h-16 w-full' />
              ))}
            </div>
          ) : error ? (
            <Alert variant='destructive'>
              <AlertCircle className='h-4 w-4' />
              <AlertDescription>
                Failed to load sync history: {error.message}
              </AlertDescription>
            </Alert>
          ) : recentJobs.length > 0 ? (
            <div className='space-y-3'>
              {recentJobs.map(job => (
                <div
                  key={job.id}
                  className='flex flex-col justify-between gap-2 rounded-lg border p-3 sm:flex-row sm:items-center'
                  data-testid='sync-job-item'
                >
                  <div className='space-y-1'>
                    <div className='flex items-center gap-2'>
                      <Badge
                        variant={getSyncStatusVariant(job.attributes.status)}
                      >
                        {job.attributes.status}
                      </Badge>
                      <span className='text-sm font-medium'>
                        {job.attributes.syncType} sync
                      </span>
                    </div>
                    <p className='text-muted-foreground text-sm'>
                      {formatDateSafely(job.attributes.createdAt)}
                    </p>
                    {job.attributes.errorMessage && (
                      <p className='text-destructive mt-1 text-sm'>
                        {job.attributes.errorMessage}
                      </p>
                    )}
                  </div>
                  {job.attributes.contactsProcessed != null && (
                    <div className='text-sm sm:text-right'>
                      <p>{job.attributes.contactsProcessed} processed</p>
                      {job.attributes.contactsCreated != null && (
                        <p className='text-muted-foreground'>
                          {job.attributes.contactsCreated} created
                        </p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className='text-muted-foreground py-4 text-center'>
              No sync jobs found
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
