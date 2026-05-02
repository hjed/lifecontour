import { useState } from 'react';
import { Activity, ServerCrash, Cpu } from 'lucide-react';
import { useIntegrationHealth, useConsumerLag } from '@/lib/api/integrations';
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

function formatTimeSafely(dateString: string | null): string {
  if (!dateString) return 'Never';
  try {
    return format(new Date(dateString), 'p', { locale: enAU });
  } catch {
    return 'Invalid time';
  }
}

export interface HealthStatusProps {
  integrationId: string;
}

export function HealthStatus({
  integrationId: _integrationId,
}: HealthStatusProps) {
  const [open, setOpen] = useState(false);
  const {
    data: healthData,
    isLoading: healthLoading,
    error: healthError,
  } = useIntegrationHealth({ enabled: open });
  const {
    data: lagData,
    isLoading: lagLoading,
    error: lagError,
  } = useConsumerLag({ enabled: open });

  const health = healthData?.data?.attributes;
  const isLoading = healthLoading || lagLoading;
  const error = healthError || lagError;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' size='sm' className='gap-2'>
          <Activity className='h-4 w-4' />
          Health Status
        </Button>
      </DialogTrigger>
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            <Cpu className='h-5 w-5 text-blue-500' />
            Worker & Connection Health
          </DialogTitle>
        </DialogHeader>

        <div className='mt-4 space-y-4'>
          {isLoading ? (
            <div className='space-y-2'>
              <Skeleton className='h-8 w-full' />
              <Skeleton className='h-8 w-full' />
              <Skeleton className='h-8 w-full' />
            </div>
          ) : error ? (
            <Alert variant='destructive'>
              <ServerCrash className='h-4 w-4' />
              <AlertDescription>
                Failed to load health status: {error.message}
              </AlertDescription>
            </Alert>
          ) : (
            <div className='space-y-4'>
              {health && (
                <div className='space-y-3 rounded-md border p-4'>
                  <h4 className='text-sm font-semibold'>System Status</h4>
                  <div className='flex items-center justify-between text-sm'>
                    <span>Overall</span>
                    <Badge
                      variant={
                        health.overall === 'healthy' ? 'default' : 'destructive'
                      }
                    >
                      {health.overall}
                    </Badge>
                  </div>
                  <div className='flex items-center justify-between text-sm'>
                    <span>Worker Status</span>
                    <div className='flex items-center gap-2'>
                      <Badge
                        variant={
                          health.worker.status === 'healthy'
                            ? 'default'
                            : 'destructive'
                        }
                      >
                        {health.worker.status}
                      </Badge>
                    </div>
                  </div>
                  <div className='flex items-center justify-between text-sm'>
                    <span className='text-muted-foreground'>
                      Last Heartbeat
                    </span>
                    <span>
                      {formatTimeSafely(health.worker.lastSeen || null)}
                    </span>
                  </div>
                </div>
              )}

              <div className='space-y-3 rounded-md border p-4'>
                <h4 className='text-sm font-semibold'>
                  Event Stream Consumers
                </h4>
                {lagData && lagData.length > 0 ? (
                  lagData.map((group, i) => (
                    <div
                      key={i}
                      className='flex flex-col gap-1 border-t pt-2 text-sm first:border-0 first:pt-0'
                    >
                      <div className='flex items-center justify-between'>
                        <span className='text-muted-foreground font-medium'>
                          {group.name}
                        </span>
                        <Badge
                          variant={
                            (group.lag ?? group.pending ?? 0) > 0
                              ? 'secondary'
                              : 'default'
                          }
                        >
                          Lag: {group.lag ?? group.pending ?? 0}
                        </Badge>
                      </div>
                      <div className='text-muted-foreground flex justify-between text-xs'>
                        <span>Consumers: {group.consumers}</span>
                        <span>Pending: {group.pending}</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className='text-muted-foreground text-sm'>
                    No consumer groups active.
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
